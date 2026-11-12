"""AI pipeline: understanding -> evaluation -> generation -> independent validation -> regeneration.

Each stage is a separate model call with a strict JSON schema. Deterministic checks run
first wherever a requirement is measurable; the AI reviewer judges semantics only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ai import prompts as P
from app.ai.providers import AIConfigError, AIError, AIRefusalError, LLMProvider, Usage, make_provider, resolve_api_key
from app.db import SessionLocal
from app.models import (
    AIJob,
    AIUsageLog,
    AuditResult,
    MetadataVersion,
    Page,
    PageAnalysis,
    PageContent,
    Project,
    ProviderCredential,
    ValidationResult,
)
from app.security import decrypt_secret
from app.seo import text as tx
from app.seo.audit import audit_existing_page, build_existing_site_index, facts_for, save_audit, score
from app.seo.guidelines import ProjectContext, build_context
from app.seo.rules import SEVERITY_ORDER, PageFacts, SiteIndex, check_pair

log = logging.getLogger(__name__)

DEFAULT_AI_SETTINGS = {
    "provider": None,  # falls back to DEFAULT_AI_PROVIDER
    "model": None,
    "effort": "medium",
    "max_attempts": 3,
    "concurrency": 3,
    "min_words": 40,
    "include_non_indexable": False,
}


def ai_settings_for(project: Project) -> dict:
    from app.config import get_settings

    s = {**DEFAULT_AI_SETTINGS, **{k: v for k, v in (project.ai_settings or {}).items() if v not in (None, "")}}
    s["provider"] = s["provider"] or get_settings().default_ai_provider
    s["max_attempts"] = max(1, min(int(s["max_attempts"]), 6))
    s["concurrency"] = max(1, min(int(s["concurrency"]), 10))
    return s


def _fp(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def page_payload(page: Page, pc: PageContent, ctx: ProjectContext) -> dict:
    return {
        "url": page.url, "title": pc.title, "meta_description": pc.meta_description, "og_title": pc.og_title,
        "headings": pc.headings or [], "intro": pc.intro, "content": pc.main_content, "word_count": pc.word_count,
        "lang": pc.lang, "heuristic_page_type": pc.heuristic_page_type,
        "structured_data_types": pc.structured_data_types, "site_language": ctx.language,
    }


def analysis_dict(a: PageAnalysis) -> dict:
    return {
        "page_type": a.page_type, "primary_topic": a.primary_topic, "search_intent": a.search_intent,
        "target_audience": a.target_audience, "primary_keyword": a.primary_keyword,
        "secondary_keywords": a.secondary_keywords, "entities": a.entities, "usps": a.usps,
        "key_message": a.key_message, "positioning": a.positioning,
    }


def _clamp_scores(scores: dict) -> dict:
    return {k: max(0, min(10, int(v))) for k, v in (scores or {}).items()}


def _evidence_ok(quote: str, content: str) -> bool:
    q = tx.norm(quote)
    if not q:
        return False
    c = tx.norm(content)
    if q in c:
        return True
    qt = q.split()
    # tolerate small differences: 80% of a sliding window of tokens
    if len(qt) >= 4:
        ct = c.split()
        need = int(len(qt) * 0.8)
        qs = set(qt)
        for i in range(0, max(1, len(ct) - len(qt) + 1)):
            if len(qs & set(ct[i:i + len(qt)])) >= need:
                return True
    return False


def clean_meta(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    return value.strip("\"'“”")


class PagePipeline:
    """Runs the AI stages for one page. One instance per worker thread (own DB session/provider)."""

    def __init__(self, db: Session, project: Project, ctx: ProjectContext, provider: LLMProvider, settings: dict,
                 site: SiteIndex, site_lock: threading.Lock, user_id: int | None = None):
        self.db = db
        self.project = project
        self.ctx = ctx
        self.provider = provider
        self.settings = settings
        self.site = site
        self.site_lock = site_lock
        self.user_id = user_id

    # ------------------------------------------------------------ stage 1
    def understand(self, page: Page, force: bool = False) -> PageAnalysis:
        pc = page.content
        fp = _fp(P.PROMPT_VERSION, self.provider.name, self.provider.model, pc.content_hash, pc.title,
                 pc.meta_description, self.ctx.fingerprint())
        current = self.db.execute(
            select(PageAnalysis).where(PageAnalysis.page_id == page.id, PageAnalysis.is_current.is_(True))
        ).scalars().first()
        if current and current.fingerprint == fp and not force:
            return current  # unchanged content + instructions -> no duplicate AI processing
        payload = page_payload(page, pc, self.ctx)
        if pc.word_count < int(self.settings["min_words"]) and not pc.h1:
            data = {
                "page_type": pc.heuristic_page_type or "Other", "primary_topic": "", "search_intent": "informational",
                "target_audience": "", "primary_keyword": "", "secondary_keywords": [], "entities": [], "usps": [],
                "key_message": "", "positioning": "", "content_relevance": "",
                "content_sufficient": False,
                "insufficiency_reason": f"Only {pc.word_count} words of extractable content and no H1; "
                                        "metadata cannot be written without guessing.",
            }
        else:
            data = self.provider.complete_json(
                "understanding", P.system_prompt(self.ctx, "understanding"), P.understanding_prompt(payload),
                P.UNDERSTANDING_SCHEMA, "page_understanding",
            )
        # Keep only USPs whose evidence can be found in the page.
        usps = [u["usp"] for u in data.get("usps", []) if _evidence_ok(u.get("evidence_quote", ""), pc.main_content or "")]
        self.db.execute(update(PageAnalysis).where(PageAnalysis.page_id == page.id).values(is_current=False))
        a = PageAnalysis(
            page_id=page.id, project_id=page.project_id, is_current=True,
            page_type=data["page_type"], primary_topic=data["primary_topic"], search_intent=data["search_intent"],
            target_audience=data["target_audience"], primary_keyword=data["primary_keyword"].strip(),
            secondary_keywords=[k for k in data["secondary_keywords"] if k.strip()][:6],
            entities=data["entities"][:20], usps=usps[:8], key_message=data["key_message"],
            positioning=data["positioning"], content_relevance=data["content_relevance"],
            content_sufficient=bool(data["content_sufficient"]), insufficiency_reason=data["insufficiency_reason"],
            fingerprint=fp, provider=self.provider.name, model=self.provider.model,
        )
        self.db.add(a)
        self.db.flush()
        return a

    # ------------------------------------------------------------ stage 2
    def evaluate_existing(self, page: Page, analysis: PageAnalysis) -> AuditResult | None:
        pc = page.content
        facts = facts_for(page, pc, analysis, self.ctx)
        with self.site_lock:
            rule_issues = check_pair(pc.title, pc.meta_description, self.ctx, facts, self.existing_site, "audit")
        ai_eval = None
        extra: list[dict] = []
        if (pc.title or pc.meta_description) and analysis.content_sufficient:
            res = self.provider.complete_json(
                "evaluation", P.system_prompt(self.ctx, "evaluation"),
                P.evaluation_prompt(page_payload(page, pc, self.ctx), analysis_dict(analysis), rule_issues),
                P.EVALUATION_SCHEMA, "metadata_evaluation",
            )
            ai_eval = {**_clamp_scores(res["scores"]), "summary": res["summary"]}
            for i in res["issues"]:
                extra.append({"code": "ai_" + re.sub(r"\W+", "_", i["name"].lower())[:40], "field": i["field"],
                              "name": i["name"], "severity": i["severity"], "explanation": i["explanation"],
                              "recommendation": i["recommendation"], "source": "ai", "blocking": False})
            for c in res["unsupported_claims"]:
                extra.append({"code": "ai_unsupported_claim", "field": "both", "name": "Unsupported claim",
                              "severity": "High", "explanation": f"Not supported by page content: {c}",
                              "recommendation": "Remove or substantiate the claim.", "source": "ai", "blocking": False})
        result = audit_existing_page(self.db, self.ctx, page, self.existing_site, ai_eval, extra)
        if result:
            result.issues = sorted(result.issues, key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))
        return result

    existing_site: SiteIndex | None = None

    # ------------------------------------------------------------ stages 3-5
    def _similar_pages(self, page: Page, analysis: PageAnalysis, current_title: str | None) -> list[dict]:
        """Pages whose effective metadata or keyword overlaps with this page (for differentiation)."""
        out = []
        with self.site_lock:
            ids = set()
            if current_title:
                ids |= {pid for pid, _ in self.site.near(page.id, current_title, "title", 0.6)}
                ids |= self.site.exact_title_dupes(page.id, current_title)
            if analysis.primary_keyword:
                kw_tokens = set(tx.content_tokens(analysis.primary_keyword))
                for pid, toks in self.site.tok_sets["title"].items():
                    if pid != page.id and kw_tokens and kw_tokens <= toks:
                        ids.add(pid)
                    if len(ids) > 15:
                        break
            for pid in list(ids)[:12]:
                out.append({"page_id": pid, "title": self.site.raw_titles.get(pid), "description": self.site.raw_descs.get(pid)})
        if out:
            urls = dict(self.db.execute(select(Page.id, Page.url).where(Page.id.in_([o["page_id"] for o in out]))).all())
            for o in out:
                o["url"] = urls.get(o["page_id"], "")
        return out

    def generate(self, page: Page, analysis: PageAnalysis, fields: str = "both", feedback: str = "",
                 force: bool = False) -> MetadataVersion | None:
        pc = page.content
        current = self.db.execute(
            select(MetadataVersion).where(MetadataVersion.page_id == page.id, MetadataVersion.is_current.is_(True))
        ).scalars().first()
        gen_fp = _fp(analysis.fingerprint, self.ctx.fingerprint(), pc.title, pc.meta_description, self.provider.model, fields)
        if current and current.fingerprint == gen_fp and not force and not feedback and current.source != "manual_edit":
            return current
        version_no = (self.db.execute(select(func.max(MetadataVersion.version)).where(MetadataVersion.page_id == page.id)).scalar() or 0) + 1

        if not analysis.content_sufficient:
            mv = self._save_version(page, version_no, current.title if current else "", current.description if current else "",
                                    "ai_generated", "needs_review",
                                    f"Insufficient page content: {analysis.insufficiency_reason} Write this metadata manually.",
                                    0, "", feedback, gen_fp)
            return mv

        locked = {
            "title": (page.approved_title if page.title_status == "approved" and page.approved_title else (current.title if current else "")),
            "description": (page.approved_description if page.description_status == "approved" and page.approved_description
                            else (current.description if current else "")),
        }
        if fields == "title" and not locked["description"]:
            fields = "both"
        if fields == "description" and not locked["title"]:
            fields = "both"
        facts = facts_for(page, pc, analysis, self.ctx)
        existing_audit = self.db.execute(
            select(AuditResult).where(AuditResult.page_id == page.id, AuditResult.target == "existing", AuditResult.is_current.is_(True))
        ).scalars().first()
        similar = self._similar_pages(page, analysis, pc.title)
        payload = page_payload(page, pc, self.ctx)
        adict = analysis_dict(analysis)
        feedback_list = [f for f in [feedback.strip()] if f]
        attempts: list[dict] = []
        max_attempts = int(self.settings["max_attempts"])
        title = desc = ""
        rationale = ""
        passed = False
        all_issues: list[dict] = []
        ai_scores: dict | None = None
        summary = ""
        stage = "regeneration" if (feedback or force) else "generation"
        attempt = 0
        for attempt in range(1, max_attempts + 1):
            gen = self.provider.complete_json(
                stage if attempt == 1 else "regeneration",
                P.system_prompt(self.ctx, "generation"),
                P.generation_prompt(payload, adict, existing_audit.issues if existing_audit else [], fields, locked,
                                    similar, feedback_list, attempts),
                P.GENERATION_SCHEMA, "metadata_generation",
            )
            title = clean_meta(gen["title"]) if fields != "description" else locked["title"]
            desc = clean_meta(gen["description"]) if fields != "title" else locked["description"]
            rationale = gen.get("rationale", "")
            with self.site_lock:
                rule_issues = check_pair(title, desc, self.ctx, facts, self.site, "validate")
            for c in gen.get("claims_used", []):
                if not _evidence_ok(c.get("evidence_quote", ""), (pc.main_content or "") + " " + " ".join(pc.h1 or [])):
                    rule_issues.append({
                        "code": "claim_without_evidence", "field": "both", "name": "Claim without page evidence",
                        "severity": "Critical", "explanation": f"'{c.get('claim')}' could not be matched to the page content.",
                        "recommendation": "Remove the claim or use only what the page states.", "source": "rule", "blocking": True,
                    })
            blocking = [i for i in rule_issues if i.get("blocking")]
            if blocking:
                self._record_validation(page, attempt, title, desc, False, rule_issues, {"skipped": "Deterministic checks failed; AI review not run."})
                attempts.append({"title": title, "description": desc,
                                 "problems": [f"{i['name']}: {i['explanation']}" for i in blocking]})
                all_issues = rule_issues
                summary = "Failed deterministic checks: " + "; ".join(i["name"] for i in blocking)
                continue
            review = self.provider.complete_json(
                "validation", P.system_prompt(self.ctx, "validation"),
                P.validation_prompt(payload, adict, title, desc, rule_issues),
                P.VALIDATION_SCHEMA, "metadata_validation",
            )
            ai_issues = [{"code": "ai_review", "field": i["field"], "name": i["name"], "severity": i["severity"],
                          "explanation": i["explanation"], "recommendation": i["recommendation"], "source": "ai",
                          "blocking": i["severity"] in ("Critical", "High")} for i in review["issues"]]
            for c in review["unsupported_claims"]:
                ai_issues.append({"code": "ai_unsupported_claim", "field": "both", "name": "Unsupported claim",
                                  "severity": "Critical", "explanation": c, "recommendation": "Remove the claim.",
                                  "source": "ai", "blocking": True})
            checks_failed = [k for k in ("accurate_representation", "follows_brand_guidelines", "follows_custom_instructions",
                                         "follows_page_type_rules", "keyword_usage_appropriate", "natural_language")
                             if not review.get(k, True)]
            for k in checks_failed:
                ai_issues.append({"code": f"ai_check_{k}", "field": "both", "name": k.replace("_", " ").capitalize() + ": failed",
                                  "severity": "High", "explanation": review.get("summary", ""), "recommendation": "Address the reviewer's findings.",
                                  "source": "ai", "blocking": True})
            ai_fail = review["verdict"] == "fail" or any(i["blocking"] for i in ai_issues)
            ai_scores = {**_clamp_scores(review["scores"]), "summary": review["summary"]}
            all_issues = rule_issues + ai_issues
            summary = review["summary"]
            self._record_validation(page, attempt, title, desc, not ai_fail, rule_issues, review)
            if not ai_fail:
                passed = True
                break
            attempts.append({"title": title, "description": desc,
                             "problems": [f"{i['name']}: {i['explanation']}" for i in ai_issues if i["blocking"]] or [review["summary"]]})

        status = "passed" if passed else "failed"
        if not passed:
            summary = f"Failed validation after {attempt} attempt(s); manual review required. {summary}"
        source = "ai_regenerated" if (current is not None) else "ai_generated"
        mv = self._save_version(page, version_no, title, desc, source, status, summary, attempt, rationale, feedback, gen_fp)
        all_issues.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))
        save_audit(self.db, page, "proposed", title, desc, all_issues, score(title, desc, all_issues, self.ctx, facts, ai_scores),
                   ai_scores, metadata_version_id=mv.id)
        if fields in ("both", "title") and page.title_status != "pending":
            page.title_status = "pending"
        if fields in ("both", "description") and page.description_status != "pending":
            page.description_status = "pending"
        with self.site_lock:
            self.site.add(page.id, title, desc)
        return mv

    def _record_validation(self, page, attempt, title, desc, passed, rule_issues, ai_review):
        self.db.add(ValidationResult(page_id=page.id, project_id=page.project_id, attempt=attempt, title=title,
                                     description=desc, passed=passed, deterministic_issues=rule_issues, ai_review=ai_review))

    def _save_version(self, page, version_no, title, desc, source, status, summary, attempts, rationale, feedback, fp):
        self.db.execute(update(MetadataVersion).where(MetadataVersion.page_id == page.id).values(is_current=False))
        self.db.execute(update(AuditResult).where(AuditResult.page_id == page.id, AuditResult.target == "proposed").values(is_current=False))
        mv = MetadataVersion(
            page_id=page.id, project_id=page.project_id, version=version_no, is_current=True, title=title, description=desc,
            source=source, validation_status=status, validation_summary=summary[:4000], attempts=attempts,
            rationale=rationale, feedback=feedback, guideline_version_id=self.ctx.guideline_version_id, fingerprint=fp,
            provider=self.provider.name, model=self.provider.model, created_by=self.user_id,
        )
        self.db.add(mv)
        self.db.flush()
        return mv


# --------------------------------------------------------------------- site index


def effective_site_index(db: Session, project_id: int) -> SiteIndex:
    """Approved > current proposal > existing metadata, per indexable page."""
    site = SiteIndex()
    pages = db.execute(
        select(Page.id, Page.title_status, Page.approved_title, Page.description_status, Page.approved_description)
        .where(Page.project_id == project_id, Page.status == "crawled", Page.is_indexable.is_(True))
    ).all()
    proposals = {
        mv.page_id: mv for mv in db.execute(
            select(MetadataVersion).where(MetadataVersion.project_id == project_id, MetadataVersion.is_current.is_(True))
        ).scalars()
    }
    existing = {pid: (t, d) for pid, t, d in db.execute(
        select(PageContent.page_id, PageContent.title, PageContent.meta_description).where(PageContent.project_id == project_id)
    )}
    for pid, ts, at, ds, ad in pages:
        mv = proposals.get(pid)
        t = at if ts == "approved" and at else (mv.title if mv and mv.title else existing.get(pid, (None, None))[0])
        d = ad if ds == "approved" and ad else (mv.description if mv and mv.description else existing.get(pid, (None, None))[1])
        site.add(pid, t, d)
    return site


# ---------------------------------------------------------------------- providers


def provider_for(db: Session, project: Project, user_id: int | None, on_usage) -> LLMProvider:
    s = ai_settings_for(project)
    user_key = None
    if user_id:
        cred = db.execute(
            select(ProviderCredential).where(ProviderCredential.user_id == user_id, ProviderCredential.provider == s["provider"])
        ).scalar_one_or_none()
        if cred:
            user_key = decrypt_secret(cred.encrypted_key)
    key = resolve_api_key(s["provider"], user_key)
    return make_provider(s["provider"], s["model"], key, s["effort"], on_usage)


def usage_logger(project_id: int, page_ref: dict):
    def _log(stage: str, usage: Usage, ok: bool, error: str | None):
        with SessionLocal() as db:
            db.add(AIUsageLog(project_id=project_id, page_id=page_ref.get("page_id"), stage=stage, provider=usage.provider,
                              model=usage.model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                              cache_read_tokens=usage.cache_read_tokens, cost_usd=usage.cost_usd, latency_ms=usage.latency_ms,
                              success=ok, error=error))
            db.commit()
    return _log


# ----------------------------------------------------------------------- job runner


def _job_log(job: AIJob, msg: str):
    job.log = (list(job.log or []) + [{"t": datetime.now(timezone.utc).isoformat(), "m": msg[:500]}])[-200:]


def select_pages(db: Session, project_id: int, page_ids: list[int] | None, include_non_indexable: bool) -> list[int]:
    q = select(Page.id).join(PageContent, PageContent.page_id == Page.id).where(
        Page.project_id == project_id, Page.status == "crawled")
    if page_ids:
        q = q.where(Page.id.in_(page_ids))
    elif not include_non_indexable:
        q = q.where(Page.is_indexable.is_(True))
    return [r for (r,) in db.execute(q.order_by(Page.id)).all()]


def run_ai_job(job_id: int, provider_override: LLMProvider | None = None) -> None:
    db = SessionLocal()
    try:
        job = db.get(AIJob, job_id)
        if job is None or job.status not in ("pending", "running"):
            return
        project = db.get(Project, job.project_id)
        settings = ai_settings_for(project)
        params = job.params or {}
        include_ni = params.get("include_non_indexable", settings["include_non_indexable"])
        page_ids = select_pages(db, project.id, params.get("page_ids"), include_ni)
        job.status = "running"
        job.total = len(page_ids)
        _job_log(job, f"Started {job.kind} for {len(page_ids)} page(s) using {settings['provider']}")
        db.commit()
        try:
            if provider_override is None:
                provider_for(db, project, job.created_by, None)  # validate configuration up-front
        except AIConfigError as exc:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        site = effective_site_index(db, project.id)
        existing_site = build_existing_site_index(db, project.id)
        site_lock = threading.Lock()
        progress_lock = threading.Lock()
        fatal: dict = {}
        state = {"site": site, "params": params}

        def work(pid: int):
            if fatal:
                return
            with SessionLocal() as wdb:
                st = wdb.execute(select(AIJob.status).where(AIJob.id == job_id)).scalar_one()
                if st == "cancelled":
                    return
                page_ref = {"page_id": pid}
                prj = wdb.get(Project, project.id)
                ctx = build_context(wdb, prj)  # isolated context for THIS project only
                prov = provider_override or provider_for(wdb, prj, job.created_by, usage_logger(prj.id, page_ref))
                if provider_override is not None:
                    prov.on_usage = usage_logger(prj.id, page_ref)
                params_ = state["params"]
                pipe = PagePipeline(wdb, prj, ctx, prov, settings, state["site"], site_lock, job.created_by)
                pipe.existing_site = existing_site
                page = wdb.get(Page, pid)
                outcome = "ok"
                err = None
                try:
                    force = bool(params_.get("force"))
                    analysis = pipe.understand(page, force=force and job.kind == "analyze")
                    if job.kind == "analyze":
                        pipe.evaluate_existing(page, analysis)
                    else:
                        has_eval = wdb.execute(select(AuditResult.id).where(
                            AuditResult.page_id == pid, AuditResult.target == "existing", AuditResult.is_current.is_(True),
                            AuditResult.ai_evaluated.is_(True))).first()
                        if not has_eval:
                            pipe.evaluate_existing(page, analysis)
                        fields = params_.get("fields", "both")
                        pipe.generate(page, analysis, fields=fields, feedback=params_.get("feedback", ""),
                                      force=force or job.kind == "regenerate")
                    wdb.commit()
                except AIConfigError as exc:
                    wdb.rollback()
                    fatal["error"] = str(exc)
                    outcome, err = "failed", str(exc)
                except (AIError, AIRefusalError) as exc:
                    wdb.rollback()
                    outcome, err = "failed", str(exc)
                except Exception as exc:  # noqa: BLE001
                    log.exception("AI processing failed for page %s", pid)
                    wdb.rollback()
                    outcome, err = "failed", f"{type(exc).__name__}: {exc}"
            with progress_lock, SessionLocal() as pdb:
                j = pdb.get(AIJob, job_id)
                j.processed += 1
                if outcome == "failed":
                    j.failed += 1
                    _job_log(j, f"Page {pid}: {err}")
                pdb.commit()

        with ThreadPoolExecutor(max_workers=settings["concurrency"]) as pool:
            list(pool.map(work, page_ids))

        # Website-wide duplicate pass: proposals generated concurrently can still collide.
        if job.kind in ("generate", "regenerate") and not fatal and len(page_ids) > 1:
            db.expire_all()
            site2 = effective_site_index(db, project.id)
            groups: dict[str, list[int]] = {}
            for pid in page_ids:
                t, d = site2.raw_titles.get(pid), site2.raw_descs.get(pid)
                if t and site2.exact_title_dupes(pid, t):
                    groups.setdefault("t:" + tx.norm(t), []).append(pid)
                if d and site2.exact_desc_dupes(pid, d):
                    groups.setdefault("d:" + tx.norm(d), []).append(pid)
            redo = sorted({pid for ids in groups.values() for pid in ids[1:]})
            if redo:
                db.refresh(job)
                _job_log(job, f"Differentiating {len(redo)} page(s) whose proposals duplicate another page")
                db.commit()
                state["params"] = {**params, "force": True, "feedback": (
                    "Your previous metadata duplicated another page's metadata. Differentiate it using what is unique about this page.")}
                state["site"] = site2
                with ThreadPoolExecutor(max_workers=settings["concurrency"]) as pool:
                    list(pool.map(work, redo))

        db.expire_all()
        job = db.get(AIJob, job_id)
        if fatal:
            job.status = "failed"
            job.error = fatal["error"]
        elif job.status != "cancelled":
            job.status = "completed"
        job.finished_at = datetime.now(timezone.utc)
        _job_log(job, f"Finished: {job.processed} processed, {job.failed} failed")
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("AI job failed")
        db.rollback()
        job = db.get(AIJob, job_id)
        if job:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
