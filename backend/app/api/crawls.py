import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crawler.engine import merged_settings
from app.crawler.url_utils import ensure_scheme, has_non_html_extension, in_scope, is_safe_url, normalize_url, variation_key
from app.db import get_db
from app.deps import audit, get_current_user, get_project
from app.models import CrawlJob, CrawlLog, Page, Project, User
from app.schemas import CrawlJobOut, CrawlLogOut, CrawlStartIn, ManualUrlsIn
from app.worker import dispatch

router = APIRouter(prefix="/projects/{project_id}/crawls", tags=["crawls"])

ACTIVE = ("pending", "running", "stopping")


def _job(db: Session, project: Project, job_id: int) -> CrawlJob:
    job = db.execute(select(CrawlJob).where(CrawlJob.id == job_id, CrawlJob.project_id == project.id)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Crawl job not found")
    return job


@router.get("", response_model=list[CrawlJobOut])
def list_jobs(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.execute(select(CrawlJob).where(CrawlJob.project_id == project.id).order_by(CrawlJob.id.desc()).limit(50)).scalars().all()


@router.post("", response_model=CrawlJobOut, status_code=201)
def start_crawl(body: CrawlStartIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    active = db.execute(select(CrawlJob).where(CrawlJob.project_id == project.id, CrawlJob.status.in_(ACTIVE + ("paused",)))).scalars().first()
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Crawl #{active.id} is {active.status}. Resume or stop it first.")
    settings = merged_settings(project, body.settings.model_dump() if body.settings else None)
    job = CrawlJob(project_id=project.id, status="pending", settings=settings, stats={})
    db.add(job)
    db.flush()
    # Re-crawl every known URL (content is overwritten, review history is kept).
    db.execute(update(Page).where(Page.project_id == project.id, Page.status != "duplicate")
               .values(status="queued", error=None, crawl_job_id=job.id))
    audit(db, user, project.id, "crawl.start", job_id=job.id)
    db.commit()
    job.task_id = dispatch("crawl", job.id)
    db.commit()
    db.refresh(job)
    return job


@router.get("/{job_id}", response_model=CrawlJobOut)
def get_job(job_id: int, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return _job(db, project, job_id)


@router.post("/{job_id}/pause", response_model=CrawlJobOut)
def pause(job_id: int, project: Project = Depends(get_project), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _job(db, project, job_id)
    if job.status not in ("running", "pending"):
        raise HTTPException(409, f"Cannot pause a crawl that is {job.status}")
    job.status = "paused"
    audit(db, user, project.id, "crawl.pause", job_id=job.id)
    db.commit()
    return job


@router.post("/{job_id}/resume", response_model=CrawlJobOut)
def resume(job_id: int, project: Project = Depends(get_project), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _job(db, project, job_id)
    if job.status not in ("paused", "failed"):
        raise HTTPException(409, f"Cannot resume a crawl that is {job.status}")
    job.status = "pending"
    job.error = None
    audit(db, user, project.id, "crawl.resume", job_id=job.id)
    db.commit()
    job.task_id = dispatch("crawl", job.id)
    db.commit()
    return job


@router.post("/{job_id}/stop", response_model=CrawlJobOut)
def stop(job_id: int, project: Project = Depends(get_project), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _job(db, project, job_id)
    if job.status in ("completed", "stopped"):
        raise HTTPException(409, f"Crawl is already {job.status}")
    if job.status in ("paused", "failed", "pending"):
        from datetime import datetime, timezone

        job.status = "stopped"
        job.finished_at = datetime.now(timezone.utc)
    else:
        job.status = "stopping"
    audit(db, user, project.id, "crawl.stop", job_id=job.id)
    db.commit()
    return job


@router.get("/{job_id}/logs", response_model=list[CrawlLogOut])
def logs(job_id: int, project: Project = Depends(get_project), db: Session = Depends(get_db),
         level: str | None = None, limit: int = Query(200, le=2000), offset: int = 0):
    _job(db, project, job_id)
    q = select(CrawlLog).where(CrawlLog.crawl_job_id == job_id, CrawlLog.project_id == project.id)
    if level:
        q = q.where(CrawlLog.level == level)
    return db.execute(q.order_by(CrawlLog.id.desc()).offset(offset).limit(limit)).scalars().all()


# ------------------------------------------------------------------ manual URLs


def _add_manual(db: Session, project: Project, urls: list[str], source: str) -> dict:
    s = merged_settings(project)
    existing = set(db.execute(select(Page.url).where(Page.project_id == project.id)).scalars())
    added, rejected = 0, []
    allow_private = get_settings().allow_private_networks
    for raw in urls:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        n = normalize_url(ensure_scheme(raw) if "://" not in raw and not raw.startswith("/") else raw, base=project.base_url)
        if not n:
            rejected.append({"url": raw, "reason": "Not a valid http(s) URL"})
            continue
        if not in_scope(n, project.domain, s["include_subdomains"], s.get("allowed_hosts")):
            rejected.append({"url": raw, "reason": f"Outside the project domain ({project.domain})"})
            continue
        if has_non_html_extension(n):
            rejected.append({"url": raw, "reason": "Not an HTML page (file extension)"})
            continue
        if not is_safe_url(n, allow_private):
            rejected.append({"url": raw, "reason": "Resolves to a private or reserved network address"})
            continue
        if n in existing:
            continue
        db.add(Page(project_id=project.id, url=n, variation_key=variation_key(n), source=source, depth=0))
        existing.add(n)
        added += 1
    db.commit()
    return {"added": added, "rejected": rejected[:500], "rejected_count": len(rejected)}


@router.post("/urls")
def add_urls(body: ManualUrlsIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    res = _add_manual(db, project, body.urls, "manual")
    audit(db, user, project.id, "urls.add", added=res["added"])
    db.commit()
    return res


@router.post("/urls/upload")
async def upload_urls(file: UploadFile = File(...), project: Project = Depends(get_project),
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    raw = await file.read(10_000_001)
    if len(raw) > 10_000_000:
        raise HTTPException(413, "File too large (max 10 MB)")
    text = raw.decode("utf-8-sig", errors="replace")
    urls: list[str] = []
    for row in csv.reader(io.StringIO(text)):
        for cell in row:
            cell = cell.strip()
            if cell.startswith(("http://", "https://", "/")) or "." in cell and " " not in cell:
                urls.append(cell)
                break
    if not urls:
        raise HTTPException(422, "No URLs found. Upload a .txt or .csv with one URL per line (first column).")
    res = _add_manual(db, project, urls, "upload")
    audit(db, user, project.id, "urls.upload", added=res["added"], filename=file.filename)
    db.commit()
    return res


@router.get("/summary/status")
def crawl_summary(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    rows = db.execute(select(Page.status, func.count()).where(Page.project_id == project.id).group_by(Page.status)).all()
    http = db.execute(select(Page.http_status, func.count()).where(Page.project_id == project.id, Page.http_status.is_not(None))
                      .group_by(Page.http_status)).all()
    sources = db.execute(select(Page.source, func.count()).where(Page.project_id == project.id).group_by(Page.source)).all()
    return {"by_status": dict(rows), "by_http_status": {str(k): v for k, v in http}, "by_source": dict(sources)}


@router.get("/results/pages")
def crawl_pages(project: Project = Depends(get_project), db: Session = Depends(get_db), status_filter: str | None = Query(None, alias="status"),
                q: str | None = None, limit: int = Query(100, le=1000), offset: int = 0):
    """All discovered URLs with their crawl outcome (including failures, which are never discarded)."""
    query = select(Page).where(Page.project_id == project.id)
    if status_filter == "errors":
        query = query.where((Page.status.in_(("failed", "blocked"))) | (Page.http_status >= 400))
    elif status_filter:
        query = query.where(Page.status == status_filter)
    if q:
        query = query.where(func.lower(Page.url).like(f"%{q.lower()}%"))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.execute(query.order_by(Page.id).offset(offset).limit(limit)).scalars().all()
    return {"total": total, "items": [{
        "id": p.id, "url": p.url, "status": p.status, "http_status": p.http_status, "error": p.error, "source": p.source,
        "depth": p.depth, "final_url": p.final_url, "is_indexable": p.is_indexable, "indexability_reason": p.indexability_reason,
        "rendered_with_js": p.rendered_with_js, "response_ms": p.response_ms, "attempts": p.attempts,
    } for p in rows]}
