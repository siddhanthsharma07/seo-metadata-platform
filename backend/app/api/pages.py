"""Metadata table, page detail, editing and approval workflow."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, asc, desc, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.ai.pipeline import effective_site_index
from app.db import get_db
from app.deps import audit, get_current_user, get_page, get_project
from app.models import (
    AIJob,
    ApprovalEvent,
    AuditResult,
    MetadataVersion,
    Page,
    PageAnalysis,
    PageContent,
    Project,
    User,
    ValidationResult,
)
from app.schemas import BulkIn, PageActionIn, RegenerateIn
from app.seo.audit import facts_for, save_audit, score
from app.seo.guidelines import build_context
from app.seo.rules import check_pair
from app.worker import dispatch

router = APIRouter(prefix="/projects/{project_id}/pages", tags=["pages"])

APPROVAL_BLOCKING = ("guardrail_", "format_em_dash", "format_exclamation", "format_emoji", "format_pipe",
                     "title_brand_prohibited", "title_missing", "description_missing")

EA = aliased(AuditResult)
PA = aliased(AuditResult)
AN = aliased(PageAnalysis)
MV = aliased(MetadataVersion)


def _base_query(project_id: int):
    page_type = func.coalesce(AN.page_type, PageContent.heuristic_page_type)
    q = (
        select(Page, PageContent, AN, MV, EA, PA, page_type.label("page_type"))
        .join(PageContent, PageContent.page_id == Page.id)
        .outerjoin(AN, and_(AN.page_id == Page.id, AN.is_current.is_(True)))
        .outerjoin(MV, and_(MV.page_id == Page.id, MV.is_current.is_(True)))
        .outerjoin(EA, and_(EA.page_id == Page.id, EA.target == "existing", EA.is_current.is_(True)))
        .outerjoin(PA, and_(PA.page_id == Page.id, PA.target == "proposed", PA.is_current.is_(True)))
        .where(Page.project_id == project_id, Page.status == "crawled")
    )
    return q, page_type


def _dup_subquery(project_id: int, column):
    key = func.lower(func.trim(column))
    return (select(key).where(PageContent.project_id == project_id, column.is_not(None), func.length(func.trim(column)) > 0)
            .group_by(key).having(func.count() > 1))


def _row(page: Page, pc: PageContent, an, mv, ea, pa, page_type, sno: int) -> dict:
    return {
        "id": page.id,
        "s_no": sno,
        "url": page.url,
        "page_type": page_type or "Other",
        "is_indexable": page.is_indexable,
        "primary_keyword": an.primary_keyword if an else "",
        "existing_title": pc.title,
        "existing_title_len": len(pc.title or ""),
        "proposed_title": mv.title if mv else None,
        "proposed_title_len": len(mv.title) if mv else None,
        "existing_description": pc.meta_description,
        "existing_description_len": len(pc.meta_description or ""),
        "proposed_description": mv.description if mv else None,
        "proposed_description_len": len(mv.description) if mv else None,
        "existing_score": ea.overall_score if ea else None,
        "proposed_score": pa.overall_score if pa else None,
        "issues": [{"name": i["name"], "severity": i["severity"], "field": i.get("field")} for i in (ea.issues if ea else [])][:12],
        "issue_count": len(ea.issues) if ea else 0,
        "critical_count": ea.critical_count if ea else 0,
        "proposal_source": mv.source if mv else None,
        "validation_status": mv.validation_status if mv else "not_generated",
        "title_status": page.title_status,
        "description_status": page.description_status,
        "approval_status": _approval_label(page),
        "approved_title": page.approved_title,
        "approved_description": page.approved_description,
    }


def _approval_label(page: Page) -> str:
    t, d = page.title_status, page.description_status
    if t == d:
        return t
    if "approved" in (t, d) and "rejected" not in (t, d):
        return "partially_approved"
    return "mixed"


SORTS = {
    "url": Page.url, "page_type": None, "primary_keyword": AN.primary_keyword,
    "existing_score": EA.overall_score, "proposed_score": PA.overall_score,
    "existing_title_len": func.length(PageContent.title), "proposed_title_len": func.length(MV.title),
    "existing_description_len": func.length(PageContent.meta_description),
    "proposed_description_len": func.length(MV.description), "issues": EA.critical_count, "id": Page.id,
}


@router.get("")
def list_pages(
    project: Project = Depends(get_project), db: Session = Depends(get_db),
    q: str | None = None, page_type: str | None = None,
    min_score: int | None = Query(None, ge=0, le=100), max_score: int | None = Query(None, ge=0, le=100),
    missing: str | None = Query(None, pattern="^(title|description|any)$"),
    duplicate: str | None = Query(None, pattern="^(title|description|any)$"),
    critical: bool = False,
    approval: str | None = Query(None, pattern="^(pending|approved|rejected|partially_approved)$"),
    validation: str | None = Query(None, pattern="^(passed|failed|needs_review|pending|not_generated)$"),
    indexable: bool | None = None,
    sort: str = "id", order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
):
    query, ptype = _base_query(project.id)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(Page.url).like(like), func.lower(PageContent.title).like(like),
                                func.lower(PageContent.meta_description).like(like), func.lower(MV.title).like(like),
                                func.lower(MV.description).like(like), func.lower(AN.primary_keyword).like(like)))
    if page_type:
        query = query.where(ptype == page_type)
    if min_score is not None:
        query = query.where(EA.overall_score >= min_score)
    if max_score is not None:
        query = query.where(EA.overall_score <= max_score)
    empty_t = or_(PageContent.title.is_(None), func.length(func.trim(PageContent.title)) == 0)
    empty_d = or_(PageContent.meta_description.is_(None), func.length(func.trim(PageContent.meta_description)) == 0)
    if missing == "title":
        query = query.where(empty_t)
    elif missing == "description":
        query = query.where(empty_d)
    elif missing == "any":
        query = query.where(or_(empty_t, empty_d))
    if duplicate:
        dt = func.lower(func.trim(PageContent.title)).in_(_dup_subquery(project.id, PageContent.title))
        dd = func.lower(func.trim(PageContent.meta_description)).in_(_dup_subquery(project.id, PageContent.meta_description))
        query = query.where(dt if duplicate == "title" else dd if duplicate == "description" else or_(dt, dd))
    if critical:
        query = query.where(EA.critical_count > 0)
    if approval == "partially_approved":
        query = query.where(or_(Page.title_status == "approved", Page.description_status == "approved"),
                            Page.title_status != Page.description_status)
    elif approval == "pending":
        query = query.where(or_(Page.title_status == "pending", Page.description_status == "pending"))
    elif approval:
        query = query.where(Page.title_status == approval, Page.description_status == approval)
    if validation == "not_generated":
        query = query.where(MV.id.is_(None))
    elif validation:
        query = query.where(MV.validation_status == validation)
    if indexable is not None:
        query = query.where(Page.is_indexable.is_(indexable))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    col = ptype if sort == "page_type" else SORTS.get(sort, Page.id)
    direction = desc if order == "desc" else asc
    query = query.order_by(direction(col).nulls_last(), Page.id)
    rows = db.execute(query.offset(offset).limit(limit)).all()
    return {"total": total, "items": [_row(*r, sno=offset + i + 1) for i, r in enumerate(rows)]}


@router.get("/{page_id}")
def page_detail(page_id: int, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    page = get_page(project, page_id, db)
    pc = page.content
    an = db.execute(select(PageAnalysis).where(PageAnalysis.page_id == page.id, PageAnalysis.is_current.is_(True))).scalars().first()
    audits = db.execute(select(AuditResult).where(AuditResult.page_id == page.id, AuditResult.is_current.is_(True))).scalars().all()
    versions = db.execute(select(MetadataVersion).where(MetadataVersion.page_id == page.id).order_by(MetadataVersion.version.desc())).scalars().all()
    validations = db.execute(select(ValidationResult).where(ValidationResult.page_id == page.id).order_by(ValidationResult.id.desc()).limit(30)).scalars().all()
    events = db.execute(select(ApprovalEvent).where(ApprovalEvent.page_id == page.id).order_by(ApprovalEvent.id.desc()).limit(100)).scalars().all()

    def a_out(a):
        return None if a is None else {
            "title_score": a.title_score, "description_score": a.description_score, "overall_score": a.overall_score,
            "breakdown": a.breakdown, "issues": a.issues, "ai_evaluated": a.ai_evaluated, "ai_summary": a.ai_summary,
            "created_at": a.created_at,
        }

    return {
        "page": {
            "id": page.id, "url": page.url, "status": page.status, "http_status": page.http_status, "final_url": page.final_url,
            "redirect_chain": page.redirect_chain, "is_indexable": page.is_indexable, "indexability_reason": page.indexability_reason,
            "source": page.source, "depth": page.depth, "rendered_with_js": page.rendered_with_js, "crawled_at": page.crawled_at,
            "response_ms": page.response_ms, "title_status": page.title_status, "description_status": page.description_status,
            "approved_title": page.approved_title, "approved_description": page.approved_description, "approved_at": page.approved_at,
            "duplicate_of_id": page.duplicate_of_id, "error": page.error,
        },
        "content": None if pc is None else {
            "title": pc.title, "meta_description": pc.meta_description, "canonical": pc.canonical, "meta_robots": pc.meta_robots,
            "x_robots_tag": pc.x_robots_tag, "h1": pc.h1, "h2": pc.h2, "headings": pc.headings, "lang": pc.lang,
            "og_title": pc.og_title, "og_description": pc.og_description, "word_count": pc.word_count, "intro": pc.intro,
            "main_content": pc.main_content[:20000], "structured_data_types": pc.structured_data_types, "entities": pc.entities,
            "pagination": pc.pagination, "heuristic_page_type": pc.heuristic_page_type,
        },
        "analysis": None if an is None else {
            "page_type": an.page_type, "primary_topic": an.primary_topic, "search_intent": an.search_intent,
            "target_audience": an.target_audience, "primary_keyword": an.primary_keyword,
            "secondary_keywords": an.secondary_keywords, "entities": an.entities, "usps": an.usps,
            "key_message": an.key_message, "positioning": an.positioning, "content_relevance": an.content_relevance,
            "content_sufficient": an.content_sufficient, "insufficiency_reason": an.insufficiency_reason,
            "model": an.model, "created_at": an.created_at,
        },
        "existing_audit": a_out(next((a for a in audits if a.target == "existing"), None)),
        "proposed_audit": a_out(next((a for a in audits if a.target == "proposed"), None)),
        "versions": [{
            "id": v.id, "version": v.version, "is_current": v.is_current, "title": v.title, "description": v.description,
            "source": v.source, "validation_status": v.validation_status, "validation_summary": v.validation_summary,
            "attempts": v.attempts, "rationale": v.rationale, "feedback": v.feedback, "model": v.model,
            "guideline_version_id": v.guideline_version_id, "created_at": v.created_at,
        } for v in versions],
        "validations": [{
            "id": v.id, "attempt": v.attempt, "title": v.title, "description": v.description, "passed": v.passed,
            "deterministic_issues": v.deterministic_issues, "ai_review": v.ai_review, "created_at": v.created_at,
        } for v in validations],
        "events": [{
            "id": e.id, "action": e.action, "field": e.field, "title": e.value_title, "description": e.value_description,
            "note": e.note, "user_id": e.user_id, "created_at": e.created_at,
        } for e in events],
    }


# ------------------------------------------------------------------ actions


def _current_version(db: Session, page: Page) -> MetadataVersion | None:
    return db.execute(select(MetadataVersion).where(MetadataVersion.page_id == page.id, MetadataVersion.is_current.is_(True))).scalars().first()


def _validate_manual(db: Session, project: Project, page: Page, title: str, desc: str):
    ctx = build_context(db, project)
    an = db.execute(select(PageAnalysis).where(PageAnalysis.page_id == page.id, PageAnalysis.is_current.is_(True))).scalars().first()
    facts = facts_for(page, page.content, an, ctx)
    site = effective_site_index(db, project.id)  # duplicate checks exclude the page itself
    issues = check_pair(title, desc, ctx, facts, site, "validate")
    return ctx, facts, issues


def _blocking_for(issues: list[dict], field: str) -> list[dict]:
    fields = {"both": ("title", "description", "both"), "title": ("title", "both"), "description": ("description", "both")}[field]
    return [i for i in issues if i["code"].startswith(APPROVAL_BLOCKING) and i["field"] in fields]


def _event(db, page, user, action, field, mv=None, title=None, desc=None, note=""):
    db.add(ApprovalEvent(page_id=page.id, project_id=page.project_id, user_id=user.id, action=action, field=field,
                         metadata_version_id=mv.id if mv else None, value_title=title, value_description=desc, note=note))


def apply_action(db: Session, project: Project, page: Page, user: User, body: PageActionIn) -> dict:
    mv = _current_version(db, page)
    now = datetime.now(timezone.utc)
    if body.action == "edit":
        if body.title is None and body.description is None:
            raise HTTPException(422, "Provide a title and/or description to edit")
        title = (body.title if body.title is not None else (mv.title if mv else page.content.title or "")).strip()
        desc = (body.description if body.description is not None else (mv.description if mv else page.content.meta_description or "")).strip()
        ctx, facts, issues = _validate_manual(db, project, page, title, desc)
        blocking = [i for i in issues if i.get("blocking")]
        ver = (db.execute(select(func.max(MetadataVersion.version)).where(MetadataVersion.page_id == page.id)).scalar() or 0) + 1
        db.execute(update(MetadataVersion).where(MetadataVersion.page_id == page.id).values(is_current=False))
        db.execute(update(AuditResult).where(AuditResult.page_id == page.id, AuditResult.target == "proposed").values(is_current=False))
        new = MetadataVersion(page_id=page.id, project_id=project.id, version=ver, is_current=True, title=title, description=desc,
                              source="manual_edit", validation_status="failed" if blocking else "passed",
                              validation_summary=("Deterministic checks failed: " + "; ".join(i["name"] for i in blocking)) if blocking
                              else "Passed deterministic checks (manual edit; AI review not run).",
                              attempts=0, feedback=body.note, guideline_version_id=ctx.guideline_version_id, created_by=user.id,
                              provider="", model="")
        db.add(new)
        db.flush()
        db.add(ValidationResult(metadata_version_id=new.id, page_id=page.id, project_id=project.id, attempt=0, title=title,
                                description=desc, passed=not blocking, deterministic_issues=issues, ai_review={}))
        save_audit(db, page, "proposed", title, desc, issues, score(title, desc, issues, ctx, facts), None, new.id)
        if body.title is not None:
            page.title_status = "pending"
        if body.description is not None:
            page.description_status = "pending"
        _event(db, page, user, "edit", "both", new, title, desc, body.note)
        return {"ok": True, "version": ver, "issues": issues}

    if body.action == "reset":
        page.title_status = page.description_status = "pending"
        _event(db, page, user, "reset", "both", mv, note=body.note)
        return {"ok": True}

    if body.action.startswith("reject"):
        field = {"reject": "both", "reject_title": "title", "reject_description": "description"}[body.action]
        if field in ("both", "title"):
            page.title_status = "rejected"
        if field in ("both", "description"):
            page.description_status = "rejected"
        _event(db, page, user, "reject", field, mv, note=body.note)
        return {"ok": True}

    # approvals
    field = {"approve_both": "both", "approve_title": "title", "approve_description": "description"}[body.action]
    if mv is None or (field in ("both", "title") and not mv.title) or (field in ("both", "description") and not mv.description):
        raise HTTPException(409, "There is no proposed metadata to approve for this field. Generate or edit it first.")
    _ctx, _facts, issues = _validate_manual(db, project, page, mv.title, mv.description)
    blocking = _blocking_for(issues, field)
    if blocking:
        raise HTTPException(422, {"message": "Approval blocked: the metadata violates mandatory guardrails. Edit it first.",
                                  "issues": blocking})
    if field in ("both", "title"):
        page.title_status = "approved"
        page.approved_title = mv.title
    if field in ("both", "description"):
        page.description_status = "approved"
        page.approved_description = mv.description
    page.approved_at = now
    _event(db, page, user, "approve", field, mv, mv.title if field != "description" else None,
           mv.description if field != "title" else None, body.note)
    warnings = [i for i in issues if i["severity"] in ("High", "Critical") and i not in blocking]
    return {"ok": True, "warnings": warnings}


@router.post("/{page_id}/actions")
def page_action(page_id: int, body: PageActionIn, project: Project = Depends(get_project),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    page = get_page(project, page_id, db)
    if page.content is None:
        raise HTTPException(409, "This page has not been crawled successfully")
    res = apply_action(db, project, page, user, body)
    audit(db, user, project.id, f"page.{body.action}", page_id=page.id)
    db.commit()
    return res


def _ai_job(db: Session, project: Project, user: User, kind: str, page_ids: list[int], fields: str, feedback: str) -> AIJob:
    job = AIJob(project_id=project.id, kind=kind, status="pending", created_by=user.id,
                params={"page_ids": page_ids, "fields": fields, "feedback": feedback, "force": kind == "regenerate"})
    db.add(job)
    db.flush()
    audit(db, user, project.id, f"ai.{kind}", job_id=job.id, pages=len(page_ids))
    db.commit()
    dispatch("ai", job.id)
    return job


@router.post("/{page_id}/regenerate")
def regenerate(page_id: int, body: RegenerateIn, project: Project = Depends(get_project),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    page = get_page(project, page_id, db)
    if page.content is None:
        raise HTTPException(409, "This page has not been crawled successfully")
    if body.feedback:
        _event(db, page, user, "feedback", body.fields, _current_version(db, page), note=body.feedback)
    job = _ai_job(db, project, user, "regenerate", [page.id], body.fields, body.feedback)
    return {"job_id": job.id}


@router.post("/bulk")
def bulk(body: BulkIn, project: Project = Depends(get_project), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = [pid for (pid,) in db.execute(select(Page.id).where(Page.project_id == project.id, Page.id.in_(body.page_ids))).all()]
    if not ids:
        raise HTTPException(404, "None of the selected pages belong to this project")
    if body.action in ("regenerate", "generate"):
        job = _ai_job(db, project, user, body.action, ids, body.fields, body.feedback)
        return {"job_id": job.id, "queued": len(ids)}
    done, skipped = 0, []
    for pid in ids:
        page = db.get(Page, pid)
        try:
            with db.begin_nested():
                apply_action(db, project, page, user, PageActionIn(action=body.action))
            done += 1
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else exc.detail.get("message")
            skipped.append({"page_id": pid, "url": page.url, "reason": detail})
    audit(db, user, project.id, f"bulk.{body.action}", done=done, skipped=len(skipped))
    db.commit()
    return {"done": done, "skipped": skipped}
