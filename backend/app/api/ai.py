from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.ai.pipeline import ai_settings_for
from app.ai.providers import resolve_api_key
from app.db import get_db
from app.deps import audit, get_current_user, get_project
from app.models import AIJob, AIUsageLog, Page, Project, ProviderCredential, User
from app.schemas import AIJobIn, AIJobOut
from app.seo.duplicates import duplicate_report
from app.worker import dispatch

router = APIRouter(prefix="/projects/{project_id}", tags=["ai"])


def provider_status(db: Session, project: Project, user: User) -> dict:
    s = ai_settings_for(project)
    has_user_key = db.execute(select(ProviderCredential.id).where(ProviderCredential.user_id == user.id,
                                                                  ProviderCredential.provider == s["provider"])).first()
    try:
        resolve_api_key(s["provider"], "stored" if has_user_key else None)
        ok, msg = True, ""
    except Exception as exc:  # noqa: BLE001
        ok, msg = False, str(exc)
    return {"provider": s["provider"], "model": s["model"], "configured": ok, "message": msg, "settings": s}


@router.get("/ai/status")
def ai_status(project: Project = Depends(get_project), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return provider_status(db, project, user)


@router.post("/ai/jobs", response_model=AIJobOut, status_code=201)
def create_job(body: AIJobIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    st = provider_status(db, project, user)
    if not st["configured"]:
        raise HTTPException(412, st["message"])
    running = db.execute(select(AIJob).where(AIJob.project_id == project.id,
                                             AIJob.status.in_(("pending", "running")))).scalars().all()
    if body.page_ids is None and any(not (j.params or {}).get("page_ids") for j in running):
        raise HTTPException(409, "A site-wide AI job is already running for this project.")
    if body.page_ids:
        valid = {pid for (pid,) in db.execute(select(Page.id).where(Page.project_id == project.id, Page.id.in_(body.page_ids)))}
        page_ids = [p for p in body.page_ids if p in valid]
        if not page_ids:
            raise HTTPException(404, "None of the selected pages belong to this project")
    else:
        page_ids = None
    job = AIJob(project_id=project.id, kind=body.kind, status="pending", created_by=user.id,
                params={"page_ids": page_ids, "force": body.force, "fields": body.fields, "feedback": body.feedback,
                        **({"include_non_indexable": body.include_non_indexable} if body.include_non_indexable is not None else {})})
    db.add(job)
    db.flush()
    audit(db, user, project.id, f"ai.{body.kind}", job_id=job.id)
    db.commit()
    dispatch("ai", job.id)
    db.refresh(job)
    return job


@router.get("/ai/jobs", response_model=list[AIJobOut])
def list_jobs(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.execute(select(AIJob).where(AIJob.project_id == project.id).order_by(AIJob.id.desc()).limit(50)).scalars().all()


@router.get("/ai/jobs/{job_id}", response_model=AIJobOut)
def get_job(job_id: int, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    job = db.execute(select(AIJob).where(AIJob.id == job_id, AIJob.project_id == project.id)).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "AI job not found")
    return job


@router.post("/ai/jobs/{job_id}/cancel", response_model=AIJobOut)
def cancel_job(job_id: int, project: Project = Depends(get_project), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    job = get_job(job_id, project, db)
    if job.status not in ("pending", "running"):
        raise HTTPException(409, f"Job is already {job.status}")
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    audit(db, user, project.id, "ai.cancel", job_id=job.id)
    db.commit()
    return job


@router.get("/ai/usage")
def usage(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    rows = db.execute(
        select(AIUsageLog.stage, AIUsageLog.model, func.count(), func.sum(AIUsageLog.input_tokens), func.sum(AIUsageLog.output_tokens),
               func.sum(AIUsageLog.cache_read_tokens), func.sum(AIUsageLog.cost_usd),
               func.sum(case((AIUsageLog.success.is_(False), 1), else_=0)))
        .where(AIUsageLog.project_id == project.id).group_by(AIUsageLog.stage, AIUsageLog.model)
    ).all()
    items = [{"stage": r[0], "model": r[1], "calls": r[2], "input_tokens": r[3] or 0, "output_tokens": r[4] or 0,
              "cache_read_tokens": r[5] or 0, "cost_usd": round(r[6] or 0, 4), "failed_calls": r[7] or 0} for r in rows]
    return {"items": items, "total_cost_usd": round(sum(i["cost_usd"] for i in items), 4),
            "total_calls": sum(i["calls"] for i in items),
            "total_tokens": sum(i["input_tokens"] + i["output_tokens"] + i["cache_read_tokens"] for i in items)}


@router.get("/duplicates")
def duplicates(source: str = "existing", project: Project = Depends(get_project), db: Session = Depends(get_db)):
    if source not in ("existing", "proposed"):
        raise HTTPException(422, "source must be 'existing' or 'proposed'")
    return duplicate_report(db, project.id, source)
