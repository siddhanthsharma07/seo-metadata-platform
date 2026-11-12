"""Transparent 0-100 metadata scoring + existing metadata audit.

Scores are an internal quality assessment. They do not predict rankings or CTR.

Title score (100):      length 20 | display width 10 | primary keyword 20 | relevance 20 |
                        uniqueness 15 | brand convention 5 | writing quality 10
Description score (100): length 20 | keywords 15 | relevance 25 | uniqueness 15 |
                        value proposition / clarity 15 | natural language 10
Overall = 50% title + 50% description.
Relevance and value sub-scores use the independent AI evaluation when available and a
transparent token-overlap heuristic otherwise (the breakdown records which was used).
"""
from __future__ import annotations

import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AuditResult, Page, PageAnalysis, PageContent, Project
from app.seo import text as tx
from app.seo.guidelines import ProjectContext, build_context
from app.seo.rules import PageFacts, SiteIndex, check_pair

PENALTY = {"Critical": 1.0, "High": 0.6, "Medium": 0.35, "Low": 0.15}
ACTION_WORDS = re.compile(
    r"\b(discover|explore|find|shop|learn|get|compare|browse|book|see|read|try|choose|order|buy|"
    r"contact|request|download|view|plan|start|join|visit|apply)\b",
    re.I,
)


def heuristic_primary_keyword(ctx: ProjectContext, pc: PageContent | None, url: str) -> str:
    if pc is None:
        return ""
    text = " ".join([" ".join(pc.h1 or []), pc.title or "", pc.intro or "", (pc.main_content or "")[:4000]])
    prio = {"high": 0, "medium": 1, "low": 2}
    for k in sorted(ctx.keywords, key=lambda k: prio.get(k.get("priority", "medium"), 1)):
        applies = k.get("applies_to")
        if applies and applies not in url and applies != (pc.heuristic_page_type or ""):
            continue
        if tx.keyword_coverage(text, k["keyword"]) >= 1.0:
            return k["keyword"]
    if pc.h1:
        words = re.sub(r"[^\w\s&'-]", " ", pc.h1[0]).split()
        return " ".join(words[:6]).strip().lower()
    return ""


def facts_for(page: Page, pc: PageContent | None, analysis: PageAnalysis | None, ctx: ProjectContext) -> PageFacts:
    return PageFacts(
        page_id=page.id,
        url=page.url,
        page_type=(analysis.page_type if analysis else (pc.heuristic_page_type if pc else "Other")) or "Other",
        primary_keyword=(analysis.primary_keyword if analysis else heuristic_primary_keyword(ctx, pc, page.url)) or "",
        secondary_keywords=list(analysis.secondary_keywords or []) if analysis else [],
        h1=list(pc.h1 or []) if pc else [],
        intro=(pc.intro or "") if pc else "",
        content=((pc.main_content or "")[:8000]) if pc else "",
        usps=list(analysis.usps or []) if analysis else [],
    )


def _length_points(n: int, lo: int, hi: int, full: int) -> float:
    if lo <= n <= hi:
        return full
    dist = lo - n if n < lo else n - hi
    if dist <= 10:
        return full * 0.6
    if dist <= 25:
        return full * 0.3
    return full * 0.1


def _relevance_heuristic(value: str, facts: PageFacts) -> float:
    vt = set(tx.content_tokens(value))
    if not vt:
        return 0.0
    page_t = set(tx.content_tokens(" ".join(facts.h1) + " " + facts.intro + " " + facts.content[:5000]))
    if not page_t:
        return 0.5
    return len(vt & page_t) / len(vt)


def _penalise(points: float, issues: list[dict], codes: tuple[str, ...]) -> float:
    for i in issues:
        if i["code"].startswith(codes):
            points *= 1 - PENALTY.get(i["severity"], 0.2)
    return points


def score(title: str | None, desc: str | None, issues: list[dict], ctx: ProjectContext, facts: PageFacts,
          ai_eval: dict | None = None) -> tuple[int, int, int, dict]:
    bd: dict = {"title": {}, "description": {}, "relevance_source": "ai" if ai_eval else "heuristic"}
    codes = {i["code"] for i in issues}

    # ---- title
    if not title or not title.strip():
        t_score = 0
        bd["title"] = {"missing": True}
    else:
        tmin, tmax = ctx.title_range
        t = title.strip()
        b = {}
        b["length"] = round(_length_points(len(t), tmin, tmax, 20), 1)
        px = tx.pixel_width(t)
        b["display_width"] = 10 if px <= 580 else (5 if px <= 620 else 0)
        if facts.primary_keyword:
            cov = tx.keyword_coverage(t, facts.primary_keyword)
            kp = 12 * cov
            if cov >= 0.99 and "title_keyword_late" not in codes:
                kp += 8
            if "title_keyword_repeated" in codes:
                kp *= 0.5
            b["keyword"] = round(kp, 1)
        else:
            b["keyword"] = 10  # neutral when no keyword is known
        if ai_eval:
            rel = (ai_eval.get("title_relevance", 5) * 0.6 + ai_eval.get("title_intent_alignment", 5) * 0.4) / 10
        else:
            rel = _relevance_heuristic(t, facts)
        b["relevance"] = round(20 * rel, 1)
        uq = 15.0
        if "title_duplicate" in codes:
            uq = 0
        elif "title_near_duplicate" in codes:
            uq = 7
        b["uniqueness"] = uq
        b["brand"] = 0 if codes & {"title_brand_repeated", "title_brand_prohibited", "title_brand_missing", "title_brand_casing"} else (
            2.5 if "title_brand_position" in codes else 5)
        q = 10.0
        if ai_eval:
            q = 10 * (ai_eval.get("title_ctr_appeal", 5) / 10) * 0.5 + 5
        q = _penalise(q, issues, ("title_keyword_stuffing", "title_generic", "guardrail", "format"))
        b["quality"] = round(q, 1)
        t_score = round(sum(b.values()))
        bd["title"] = b

    # ---- description
    if not desc or not desc.strip():
        d_score = 0
        bd["description"] = {"missing": True}
    else:
        dmin, dmax = ctx.description_range
        d = desc.strip()
        b = {}
        b["length"] = round(_length_points(len(d), dmin, dmax, 20), 1)
        if facts.primary_keyword:
            kp = 10 * min(1.0, tx.keyword_coverage(d, facts.primary_keyword) / 0.6 if tx.keyword_coverage(d, facts.primary_keyword) else 0)
            if facts.secondary_keywords and any(tx.keyword_coverage(d, s) >= 0.6 for s in facts.secondary_keywords):
                kp += 5
            elif not facts.secondary_keywords:
                kp += 2.5
            if "description_keyword_repeated" in codes:
                kp *= 0.5
            b["keywords"] = round(kp, 1)
        else:
            b["keywords"] = 8
        if ai_eval:
            rel = (ai_eval.get("description_relevance", 5) * 0.6 + ai_eval.get("description_intent_alignment", 5) * 0.4) / 10
        else:
            rel = _relevance_heuristic(d, facts)
        b["relevance"] = round(25 * rel, 1)
        b["uniqueness"] = 0 if "description_duplicate" in codes else (7 if "description_near_duplicate" in codes else 15)
        if ai_eval:
            v = 15 * ((ai_eval.get("description_value_clarity", 5) + ai_eval.get("description_ctr_appeal", 5)) / 20)
        else:
            v = 7.5 + (4 if ACTION_WORDS.search(d) else 0) + (3.5 if len(tx.content_tokens(d)) >= 10 else 0)
        b["value_clarity"] = round(min(15, v), 1)
        nat = 10.0 if not ai_eval else 10 * ai_eval.get("naturalness", 7) / 10
        nat = _penalise(nat, issues, ("description_keyword_stuffing", "description_unsupported", "guardrail", "format",
                                      "description_repetitive"))
        b["natural_language"] = round(nat, 1)
        d_score = round(sum(b.values()))
        bd["description"] = b

    # Blocking guardrail violations cap the score: content that breaks mandatory rules can't score well.
    if any(i["severity"] == "Critical" and i["field"] in ("title", "both") for i in issues) and t_score:
        t_score = min(t_score, 40)
    if any(i["severity"] == "Critical" and i["field"] in ("description", "both") for i in issues) and d_score:
        d_score = min(d_score, 40)
    t_score = max(0, min(100, t_score))
    d_score = max(0, min(100, d_score))
    overall = round(0.5 * t_score + 0.5 * d_score)
    return t_score, d_score, overall, bd


def build_existing_site_index(db: Session, project_id: int) -> SiteIndex:
    site = SiteIndex()
    rows = db.execute(
        select(Page.id, PageContent.title, PageContent.meta_description)
        .join(PageContent, PageContent.page_id == Page.id)
        .where(Page.project_id == project_id, Page.status == "crawled", Page.is_indexable.is_(True))
    ).all()
    for pid, t, d in rows:
        site.add(pid, t, d)
    return site


def save_audit(db: Session, page: Page, target: str, title, desc, issues, scores, ai_eval: dict | None = None,
               metadata_version_id: int | None = None) -> AuditResult:
    t_s, d_s, o_s, bd = scores
    if target == "existing":
        db.execute(update(AuditResult).where(AuditResult.page_id == page.id, AuditResult.target == "existing")
                   .values(is_current=False))
    res = AuditResult(
        page_id=page.id, project_id=page.project_id, target=target, metadata_version_id=metadata_version_id,
        title_score=t_s, description_score=d_s, overall_score=o_s, breakdown=bd, issues=issues,
        critical_count=sum(1 for i in issues if i["severity"] == "Critical"),
        high_count=sum(1 for i in issues if i["severity"] == "High"),
        ai_evaluated=bool(ai_eval), ai_summary=(ai_eval or {}).get("summary", ""),
    )
    db.add(res)
    return res


def audit_existing_page(db: Session, ctx: ProjectContext, page: Page, site: SiteIndex, ai_eval: dict | None = None,
                        extra_issues: list[dict] | None = None) -> AuditResult | None:
    pc = page.content
    if pc is None:
        return None
    analysis = db.execute(
        select(PageAnalysis).where(PageAnalysis.page_id == page.id, PageAnalysis.is_current.is_(True))
    ).scalars().first()
    facts = facts_for(page, pc, analysis, ctx)
    issues = check_pair(pc.title, pc.meta_description, ctx, facts, site if page.is_indexable else None, "audit")
    if extra_issues:
        issues.extend(extra_issues)
    scores = score(pc.title, pc.meta_description, issues, ctx, facts, ai_eval)
    return save_audit(db, page, "existing", pc.title, pc.meta_description, issues, scores, ai_eval)


def audit_project_existing(db: Session, project_id: int) -> int:
    """Deterministic audit of every crawled page's existing metadata (no AI needed)."""
    project = db.get(Project, project_id)
    ctx = build_context(db, project)
    site = build_existing_site_index(db, project_id)
    pages = db.execute(select(Page).where(Page.project_id == project_id, Page.status == "crawled")).scalars().all()
    n = 0
    for page in pages:
        if audit_existing_page(db, ctx, page, site):
            n += 1
    db.flush()
    return n
