from sqlalchemy import select

from app.crawler.engine import merged_settings, run_crawl_job
from app.models import AuditResult, CrawlJob, CrawlLog, Page, Project, User


def make_project(db, site, **crawl):
    u = User(email="c@example.com", hashed_password="x")
    db.add(u)
    db.flush()
    p = Project(owner_id=u.id, name="Acme Outdoor", domain="127.0.0.1", base_url=site.base + "/",
                crawl_settings={"delay_ms": 0, "render_js": "never", "concurrency": 4, **crawl}, ai_settings={})
    db.add(p)
    db.commit()
    return p


def start(db, p):
    job = CrawlJob(project_id=p.id, status="pending", settings=merged_settings(p))
    db.add(job)
    db.commit()
    run_crawl_job(job.id)
    db.expire_all()
    return db.get(CrawlJob, job.id)


def pages_by_path(db, p, base):
    return {pg.url.replace(base, ""): pg for pg in db.execute(select(Page).where(Page.project_id == p.id)).scalars()}


def test_full_crawl_discovers_and_classifies(db, site):
    p = make_project(db, site)
    job = start(db, p)
    assert job.status == "completed", job.error
    pages = pages_by_path(db, p, site.base)

    # discovered via sitemap index + links, tracking params removed, no external/mailto/pdf URLs
    for path in ("/", "/products/ridge-runner-2", "/products/summit-gtx", "/category/trail-shoes/",
                 "/category/trail-shoes/?page=2", "/blog/how-to-choose-trail-shoes", "/about-us", "/contact"):
        assert path in pages, f"{path} not discovered; got {sorted(pages)}"
        assert pages[path].status == "crawled", (path, pages[path].status, pages[path].error)
    assert not any("utm_" in u or "gclid" in u or "external" in u or u.endswith(".pdf") for u in pages)

    assert pages["/private/admin"].status == "blocked"  # robots.txt
    assert "/private/admin" not in site.hits
    assert pages["/missing-page"].status == "failed" and pages["/missing-page"].http_status == 404
    assert pages["/server-error"].http_status == 500
    assert pages["/server-error"].attempts >= 2  # 5xx retried
    assert pages["/old-page"].status == "redirected" and pages["/old-page"].http_status == 301
    assert pages["/noindex-page"].is_indexable is False
    assert pages["/products/ridge-runner-2"].content.meta_description is None
    assert pages["/products/ridge-runner-2"].content.heuristic_page_type == "Product"
    assert pages["/category/trail-shoes/?page=2"].source == "pagination"

    # failed URLs are logged, never silently discarded
    logs = db.execute(select(CrawlLog).where(CrawlLog.crawl_job_id == job.id)).scalars().all()
    assert any("404" in l.message for l in logs) and any(l.level == "error" for l in logs)

    # deterministic audit ran after the crawl
    audits = {a.page_id: a for a in db.execute(select(AuditResult)).scalars()}
    rr = audits[pages["/products/ridge-runner-2"].id]
    assert any(i["code"] == "description_missing" for i in rr.issues)
    assert any(i["code"] == "title_duplicate" for i in rr.issues)  # shared with summit-gtx
    blog = audits[pages["/blog/how-to-choose-trail-shoes"].id]
    assert blog.title_score == 0 and blog.issues[0]["severity"] == "Critical"


def test_max_urls_limit_marks_rest_skipped(db, site):
    p = make_project(db, site, max_urls=3)
    job = start(db, p)
    assert job.status == "completed"
    pages = db.execute(select(Page).where(Page.project_id == p.id)).scalars().all()
    processed = [pg for pg in pages if pg.status in ("crawled", "failed", "blocked", "redirected")]
    assert len(processed) <= 3
    assert any(pg.status == "skipped" and "limit" in (pg.error or "") for pg in pages)


def test_resume_after_interruption(db, site):
    p = make_project(db, site)
    job = start(db, p)
    about = db.execute(select(Page).where(Page.project_id == p.id, Page.url.like("%/about-us"))).scalar_one()
    contact = db.execute(select(Page).where(Page.project_id == p.id, Page.url.like("%/contact"))).scalar_one()
    about.status = "fetching"  # worker died mid-fetch
    contact.status = "queued"
    job.status = "paused"
    db.commit()
    before = site.hits.get("/contact", 0)
    job.status = "pending"  # what the resume endpoint does before dispatching
    db.commit()
    run_crawl_job(job.id)
    db.expire_all()
    assert db.get(CrawlJob, job.id).status == "completed"
    assert db.get(Page, about.id).status == "crawled"
    assert db.get(Page, contact.id).status == "crawled"
    assert site.hits["/contact"] == before + 1
