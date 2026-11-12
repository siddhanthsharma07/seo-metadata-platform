from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_project
from app.models import AIJob, AuditResult, CrawlJob, MetadataVersion, Page, PageAnalysis, PageContent, Project, User
from app.seo.guidelines import PAGE_TYPES

router = APIRouter(tags=["dashboard"])


@router.get("/meta/page-types")
def page_types(_user: User = Depends(get_current_user)):
    return PAGE_TYPES


def _dupe_count(db: Session, project_id: int, col) -> int:
    key = func.lower(func.trim(col))
    sub = (select(key.label("k"), func.count().label("n"))
           .join(Page, Page.id == PageContent.page_id)
           .where(PageContent.project_id == project_id, col.is_not(None), func.length(func.trim(col)) > 0,
                  Page.status == "crawled", Page.is_indexable.is_(True))
           .group_by(key).having(func.count() > 1).subquery())
    return db.execute(select(func.coalesce(func.sum(sub.c.n), 0))).scalar_one()


@router.get("/projects/{project_id}/dashboard")
def dashboard(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    pid = project.id
    c = lambda q: db.execute(q).scalar_one()  # noqa: E731
    crawled_q = select(func.count()).select_from(Page).where(Page.project_id == pid, Page.status == "crawled")
    base = select(func.count()).select_from(PageContent).join(Page, Page.id == PageContent.page_id).where(
        Page.project_id == pid, Page.status == "crawled")
    empty = lambda col: or_(col.is_(None), func.length(func.trim(col)) == 0)  # noqa: E731
    ea = select(func.avg(AuditResult.overall_score)).where(AuditResult.project_id == pid, AuditResult.target == "existing", AuditResult.is_current.is_(True))
    pa = select(func.avg(AuditResult.overall_score)).where(AuditResult.project_id == pid, AuditResult.target == "proposed", AuditResult.is_current.is_(True))
    needs = select(func.count()).select_from(AuditResult).where(
        AuditResult.project_id == pid, AuditResult.target == "existing", AuditResult.is_current.is_(True),
        or_(AuditResult.overall_score < 70, AuditResult.critical_count > 0, AuditResult.high_count > 0))
    mv = select(func.count()).select_from(MetadataVersion).where(MetadataVersion.project_id == pid, MetadataVersion.is_current.is_(True))
    pending = select(func.count()).select_from(Page).join(
        MetadataVersion, and_(MetadataVersion.page_id == Page.id, MetadataVersion.is_current.is_(True))).where(
        Page.project_id == pid, or_(Page.title_status == "pending", Page.description_status == "pending"))
    approved = select(func.count()).select_from(Page).where(Page.project_id == pid, Page.title_status == "approved",
                                                            Page.description_status == "approved")
    partial = select(func.count()).select_from(Page).where(Page.project_id == pid, Page.title_status != Page.description_status,
                                                           or_(Page.title_status == "approved", Page.description_status == "approved"))
    rejected = select(func.count()).select_from(Page).where(Page.project_id == pid, or_(Page.title_status == "rejected", Page.description_status == "rejected"))
    vstat = dict(db.execute(select(MetadataVersion.validation_status, func.count()).where(
        MetadataVersion.project_id == pid, MetadataVersion.is_current.is_(True)).group_by(MetadataVersion.validation_status)).all())
    status_counts = dict(db.execute(select(Page.status, func.count()).where(Page.project_id == pid).group_by(Page.status)).all())
    http_errors = c(select(func.count()).select_from(Page).where(Page.project_id == pid, Page.http_status >= 400))
    ptypes = db.execute(
        select(func.coalesce(PageAnalysis.page_type, PageContent.heuristic_page_type, literal_column("'Other'")), func.count())
        .select_from(PageContent).join(Page, Page.id == PageContent.page_id)
        .outerjoin(PageAnalysis, and_(PageAnalysis.page_id == Page.id, PageAnalysis.is_current.is_(True)))
        .where(Page.project_id == pid, Page.status == "crawled")
        .group_by(func.coalesce(PageAnalysis.page_type, PageContent.heuristic_page_type, literal_column("'Other'")))
    ).all()
    buckets = db.execute(
        select(AuditResult.target, func.floor(AuditResult.overall_score / literal_column("20")), func.count())
        .where(AuditResult.project_id == pid, AuditResult.is_current.is_(True))
        .group_by(AuditResult.target, func.floor(AuditResult.overall_score / literal_column("20")))
    ).all()
    dist = {"existing": [0] * 5, "proposed": [0] * 5}
    for target, b, n in buckets:
        dist[target][min(4, int(b or 0))] += n
    last_crawl = db.execute(select(CrawlJob).where(CrawlJob.project_id == pid).order_by(CrawlJob.id.desc())).scalars().first()
    last_ai = db.execute(select(AIJob).where(AIJob.project_id == pid).order_by(AIJob.id.desc())).scalars().first()
    avg_e, avg_p = c(ea), c(pa)
    return {
        "total_discovered": sum(status_counts.values()),
        "crawled": c(crawled_q),
        "status_counts": status_counts,
        "http_errors": http_errors,
        "missing_titles": c(base.where(empty(PageContent.title))),
        "missing_descriptions": c(base.where(empty(PageContent.meta_description))),
        "duplicate_titles": _dupe_count(db, pid, PageContent.title),
        "duplicate_descriptions": _dupe_count(db, pid, PageContent.meta_description),
        "needs_improvement": c(needs),
        "generated": c(mv),
        "approved": c(approved),
        "partially_approved": c(partial),
        "rejected": c(rejected),
        "pending_review": c(pending),
        "validation": vstat,
        "avg_existing_score": round(float(avg_e), 1) if avg_e is not None else None,
        "avg_proposed_score": round(float(avg_p), 1) if avg_p is not None else None,
        "page_types": {k: v for k, v in ptypes},
        "score_distribution": dist,
        "last_crawl": None if not last_crawl else {"id": last_crawl.id, "status": last_crawl.status, "stats": last_crawl.stats,
                                                   "finished_at": last_crawl.finished_at, "created_at": last_crawl.created_at},
        "last_ai_job": None if not last_ai else {"id": last_ai.id, "kind": last_ai.kind, "status": last_ai.status,
                                                 "processed": last_ai.processed, "total": last_ai.total, "failed": last_ai.failed},
    }


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = db.execute(select(Project).where(Project.owner_id == user.id).order_by(Project.created_at.desc())).scalars().all()
    out = []
    for p in projects:
        crawled = db.execute(select(func.count()).select_from(Page).where(Page.project_id == p.id, Page.status == "crawled")).scalar_one()
        approved = db.execute(select(func.count()).select_from(Page).where(Page.project_id == p.id, Page.title_status == "approved",
                                                                           Page.description_status == "approved")).scalar_one()
        avg = db.execute(select(func.avg(AuditResult.overall_score)).where(AuditResult.project_id == p.id, AuditResult.target == "existing",
                                                                           AuditResult.is_current.is_(True))).scalar_one()
        last = db.execute(select(CrawlJob.status).where(CrawlJob.project_id == p.id).order_by(CrawlJob.id.desc())).scalars().first()
        out.append({"id": p.id, "name": p.name, "domain": p.domain, "crawled": crawled, "approved": approved,
                    "avg_existing_score": round(float(avg), 1) if avg is not None else None, "last_crawl_status": last})
    return out
