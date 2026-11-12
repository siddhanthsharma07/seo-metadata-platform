"""Crawl engine.

The frontier lives in the ``pages`` table (status=queued), so a crawl can be paused,
resumed after a worker restart, or stopped at any point without losing progress.
Fetching happens concurrently per batch; DB writes happen between batches.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crawler.discovery import RobotsInfo, discover_sitemaps, load_robots
from app.crawler.extractor import extract, indexability
from app.crawler.fetcher import Fetcher, FetchResult, JSRenderer
from app.crawler.url_utils import (
    has_non_html_extension,
    in_scope,
    is_pagination_url,
    matches_any,
    normalize_url,
    variation_key,
)
from app.db import SessionLocal
from app.models import CrawlJob, CrawlLog, GuidelineVersion, Page, PageContent, Project

log = logging.getLogger(__name__)

DEFAULT_CRAWL_SETTINGS = {
    "max_urls": 500,
    "max_depth": 5,
    "concurrency": 4,
    "delay_ms": 500,
    "max_retries": 2,
    "respect_robots": True,
    "use_sitemaps": True,
    "follow_links": True,
    "follow_canonicals": True,
    "include_subdomains": False,
    "allowed_hosts": [],
    "render_js": "auto",  # never | auto | always
    "exclude_patterns": [],
    "include_patterns": [],
    "strip_query_params": [],
    "ignore_query_strings": False,
}


def merged_settings(project: Project, overrides: dict | None = None) -> dict:
    s = dict(DEFAULT_CRAWL_SETTINGS)
    s.update({k: v for k, v in (project.crawl_settings or {}).items() if v is not None})
    s.update({k: v for k, v in (overrides or {}).items() if v is not None})
    s["max_urls"] = max(1, min(int(s["max_urls"]), 100_000))
    s["max_depth"] = max(0, min(int(s["max_depth"]), 50))
    s["concurrency"] = max(1, min(int(s["concurrency"]), 32))
    s["delay_ms"] = max(0, min(int(s["delay_ms"]), 60_000))
    s["max_retries"] = max(0, min(int(s["max_retries"]), 5))
    return s


class RateLimiter:
    """Enforces a minimum interval between request starts (politeness delay)."""

    def __init__(self, interval_s: float):
        self.interval = interval_s
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self):
        if self.interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._last + self.interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class CrawlRunner:
    def __init__(self, job_id: int, fetcher_transport=None):
        self.job_id = job_id
        self.app_settings = get_settings()
        self.fetcher_transport = fetcher_transport
        self.known: dict[str, int] = {}
        self.variations: dict[str, int] = {}
        self._brand_cache: dict[int, list[str]] = {}
        self.run_token: str | None = None

    # ------------------------------------------------------------------ helpers
    def _log(self, db: Session, project_id: int, message: str, level: str = "info", url: str | None = None):
        db.add(CrawlLog(crawl_job_id=self.job_id, project_id=project_id, level=level, message=message[:2000], url=url))

    def _stats(self, db: Session, project_id: int) -> dict:
        rows = db.execute(
            select(Page.status, func.count()).where(Page.project_id == project_id).group_by(Page.status)
        ).all()
        by_status = {s: c for s, c in rows}
        return {
            "discovered": sum(by_status.values()),
            "by_status": by_status,
            "crawled": by_status.get("crawled", 0),
            "failed": by_status.get("failed", 0),
            "queued": by_status.get("queued", 0) + by_status.get("fetching", 0),
        }

    def _add_url(self, db: Session, project: Project, url: str, source: str, depth: int, s: dict,
                 parent_url: str | None = None) -> Page | None:
        n = normalize_url(url, strip_query_params=set(s.get("strip_query_params") or []))
        if not n:
            return None
        if s.get("ignore_query_strings") and "?" in n and not is_pagination_url(n):
            n = n.split("?", 1)[0]
        if n in self.known:
            return None
        if not in_scope(n, project.domain, s["include_subdomains"], s.get("allowed_hosts")):
            return None
        if has_non_html_extension(n):
            return None
        if s.get("include_patterns") and not matches_any(n, s["include_patterns"]) and source not in ("seed", "manual", "upload"):
            return None
        if matches_any(n, s.get("exclude_patterns")):
            return None
        vk = variation_key(n)
        page = Page(project_id=project.id, crawl_job_id=self.job_id, url=n, variation_key=vk, source=source, depth=depth)
        if vk in self.variations and source not in ("manual", "upload"):
            page.status = "duplicate"
            page.duplicate_of_id = self.variations[vk]
            page.error = "URL variation of an already discovered URL (case, www, protocol or trailing slash)"
        db.add(page)
        db.flush()
        self.known[n] = page.id
        self.variations.setdefault(vk, page.id)
        return page

    def _job_status(self, db: Session) -> str:
        status, token = db.execute(select(CrawlJob.status, CrawlJob.run_token).where(CrawlJob.id == self.job_id)).one()
        if token != self.run_token:
            return "superseded"  # a newer worker took over this job (e.g. quick pause/resume)
        return status

    # --------------------------------------------------------------------- run
    def run(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        db = SessionLocal()
        fetcher = None
        renderer = None
        try:
            job = db.get(CrawlJob, self.job_id)
            if job is None:
                return
            project = db.get(Project, job.project_id)
            s = job.settings or merged_settings(project)
            ua = self.app_settings.crawler_user_agent
            self.run_token = uuid.uuid4().hex
            job.run_token = self.run_token
            job.status = "running"
            job.started_at = job.started_at or datetime.now(timezone.utc)
            job.error = None
            db.execute(update(Page).where(Page.project_id == project.id, Page.status == "fetching").values(status="queued"))
            db.commit()

            fetcher = Fetcher(
                user_agent=ua,
                timeout=self.app_settings.crawler_timeout_seconds,
                max_bytes=self.app_settings.crawler_max_bytes,
                max_retries=s["max_retries"],
                allow_private=self.app_settings.allow_private_networks,
                transport=self.fetcher_transport,
            )
            if s["render_js"] in ("auto", "always"):
                renderer = JSRenderer(ua, self.app_settings.allow_private_networks, self.app_settings.playwright_chromium_path)

            for pid, url, vk in db.execute(select(Page.id, Page.url, Page.variation_key).where(Page.project_id == project.id)):
                self.known[url] = pid
                self.variations.setdefault(vk, pid)

            robots = RobotsInfo(url="", status=None, parser=None)
            if s["respect_robots"]:
                robots = await load_robots(fetcher, project.base_url, ua)
                if robots.error:
                    self._log(db, project.id, f"robots.txt: {robots.error}", "warning", robots.url)
                else:
                    self._log(db, project.id, f"robots.txt loaded (HTTP {robots.status}); {len(robots.sitemaps)} sitemap(s) declared")
            delay = s["delay_ms"] / 1000.0
            if robots.crawl_delay:
                delay = max(delay, min(robots.crawl_delay, 30.0))
            limiter = RateLimiter(delay)

            stats = dict(job.stats or {})
            if not stats.get("seeded"):
                self._add_url(db, project, project.base_url, "seed", 0, s)
                if s["use_sitemaps"]:
                    root = f"{urlsplit(project.base_url).scheme}://{urlsplit(project.base_url).netloc}"
                    candidates = robots.sitemaps or [f"{root}/sitemap.xml", f"{root}/sitemap_index.xml"]
                    sm = await discover_sitemaps(fetcher, candidates, max_urls=s["max_urls"] * 2)
                    added = 0
                    for u in sm.urls:
                        if self._add_url(db, project, u, "sitemap", 1, s):
                            added += 1
                    self._log(db, project.id, f"Sitemaps read: {len(sm.sitemaps_read)}; URLs added from sitemaps: {added}")
                    for err in sm.errors[:20]:
                        self._log(db, project.id, f"Sitemap not available: {err}", "warning")
                stats["seeded"] = True
                job.stats = stats
                db.commit()

            while True:
                status = self._job_status(db)
                if status in ("paused", "stopping", "superseded"):
                    if status == "superseded":
                        db.close()
                        return
                    break
                processed = db.execute(
                    select(func.count()).select_from(Page).where(
                        Page.project_id == project.id,
                        Page.crawl_job_id == self.job_id,
                        Page.status.in_(["crawled", "failed", "blocked", "skipped", "redirected"]),
                    )
                ).scalar_one()
                remaining_budget = s["max_urls"] - processed
                if remaining_budget <= 0:
                    n = db.execute(
                        update(Page).where(Page.project_id == project.id, Page.status == "queued")
                        .values(status="skipped", error="Not crawled: maximum URL limit for this crawl reached")
                    ).rowcount
                    if n:
                        self._log(db, project.id, f"Max URL limit ({s['max_urls']}) reached; {n} queued URLs marked as skipped", "warning")
                    db.commit()
                    break
                batch = db.execute(
                    select(Page).where(Page.project_id == project.id, Page.status == "queued")
                    .order_by(Page.depth, Page.id).limit(min(remaining_budget, s["concurrency"] * 3))
                ).scalars().all()
                if not batch:
                    break
                to_fetch: list[Page] = []
                for p in batch:
                    p.crawl_job_id = self.job_id
                    if s["respect_robots"] and not robots.allowed(p.url, ua):
                        p.status = "blocked"
                        p.error = "Disallowed by robots.txt"
                        p.is_indexable = False
                        p.indexability_reason = "Blocked by robots.txt"
                        p.crawled_at = datetime.now(timezone.utc)
                        continue
                    p.status = "fetching"
                    to_fetch.append(p)
                db.commit()

                sem = asyncio.Semaphore(s["concurrency"])

                async def fetch_one(page: Page) -> tuple[Page, FetchResult]:
                    async with sem:
                        await limiter.wait()
                        return page, await fetcher.fetch(page.url)

                results = await asyncio.gather(*(fetch_one(p) for p in to_fetch))
                for page, res in results:
                    await self._process(db, project, page, res, s, robots, renderer, limiter)
                job = db.get(CrawlJob, self.job_id)
                job.stats = {**(job.stats or {}), **self._stats(db, project.id)}
                db.commit()

            job = db.get(CrawlJob, self.job_id)
            final = job.status
            if final == "stopping":
                job.status = "stopped"
                job.finished_at = datetime.now(timezone.utc)
                self._log(db, project.id, "Crawl stopped by user")
            elif final == "paused":
                self._log(db, project.id, "Crawl paused by user")
            else:
                job.status = "completed"
                job.finished_at = datetime.now(timezone.utc)
                self._log(db, project.id, "Crawl completed")
            job.stats = {**(job.stats or {}), **self._stats(db, project.id)}
            db.commit()
            if job.status == "completed":
                from app.seo.audit import audit_project_existing

                audit_project_existing(db, project.id)
                db.commit()
        except Exception as exc:  # noqa: BLE001
            log.exception("crawl failed")
            db.rollback()
            job = db.get(CrawlJob, self.job_id)
            if job:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.finished_at = datetime.now(timezone.utc)
                self._log(db, job.project_id, f"Crawl failed: {exc}", "error")
                db.commit()
        finally:
            if fetcher:
                await fetcher.close()
            if renderer:
                await renderer.close()
            db.close()

    # ------------------------------------------------------------- per page
    async def _process(self, db: Session, project: Project, page: Page, res: FetchResult, s: dict,
                       robots: RobotsInfo, renderer: JSRenderer | None, limiter: RateLimiter) -> None:
        now = datetime.now(timezone.utc)
        page.attempts = (page.attempts or 0) + res.attempts
        page.crawled_at = now
        page.response_ms = res.elapsed_ms
        page.redirect_chain = res.redirect_chain
        page.error = None
        if res.status is None:
            page.status = "blocked" if res.blocked_reason else "failed"
            page.error = res.error
            page.is_indexable = False
            page.indexability_reason = "Not reachable"
            self._log(db, project.id, f"Fetch failed: {res.error}", "error", page.url)
            return

        target = page
        if res.redirect_chain:
            page.http_status = res.redirect_chain[0]["status"]
            page.final_url = res.final_url
            page.status = "redirected"
            page.is_indexable = False
            page.indexability_reason = f"Redirects to {res.final_url}"
            final_norm = normalize_url(res.final_url)
            if not final_norm or not in_scope(final_norm, project.domain, s["include_subdomains"], s.get("allowed_hosts")):
                self._log(db, project.id, f"Redirects out of scope to {res.final_url}", "warning", page.url)
                return
            existing_id = self.known.get(final_norm)
            if existing_id:
                existing = db.get(Page, existing_id)
                if existing.status not in ("queued",):
                    return  # already handled
                target = existing
            else:
                target = self._add_url(db, project, final_norm, "redirect", page.depth, s)
                if target is None:
                    return
            target.crawl_job_id = self.job_id
            target.crawled_at = now
            target.response_ms = res.elapsed_ms
            target.attempts = (target.attempts or 0) + 1

        target.http_status = res.status
        target.final_url = res.final_url
        target.content_type = res.content_type[:200] if res.content_type else None
        if not (200 <= res.status < 300):
            target.status = "failed"
            target.error = f"HTTP {res.status}"
            target.is_indexable = False
            target.indexability_reason = f"HTTP {res.status}"
            self._log(db, project.id, f"HTTP {res.status}", "warning" if res.status < 500 else "error", target.url)
            return
        if not res.is_html:
            target.status = "skipped"
            target.error = f"Non-HTML content type: {res.content_type}"
            target.is_indexable = None
            return

        brand_terms = self._brand_terms(db, project)
        ex = extract(res.text, res.final_url, brand_terms)
        rendered = False
        if renderer and (s["render_js"] == "always" or (s["render_js"] == "auto" and ex.looks_js_rendered)):
            await limiter.wait()
            rr = await renderer.render(res.final_url)
            if rr.text and not rr.error:
                ex2 = extract(rr.text, rr.final_url, brand_terms)
                if ex2.word_count >= ex.word_count:
                    ex, rendered = ex2, True
            elif rr.error:
                self._log(db, project.id, rr.error, "warning", target.url)
        target.rendered_with_js = rendered

        pc = db.execute(select(PageContent).where(PageContent.page_id == target.id)).scalar_one_or_none()
        if pc is None:
            pc = PageContent(page_id=target.id, project_id=project.id, content_hash=ex.content_hash)
            db.add(pc)
        for f in ("title", "meta_description", "canonical", "meta_robots", "h1", "h2", "headings", "lang", "og_title",
                  "og_description", "word_count", "intro", "main_content", "content_hash", "structured_data_types",
                  "entities", "pagination", "heuristic_page_type"):
            setattr(pc, f, getattr(ex, f))
        pc.x_robots_tag = res.headers.get("x-robots-tag")
        allowed = robots.allowed(target.url, self.app_settings.crawler_user_agent) if s["respect_robots"] else True
        idx, reason = indexability(res.status, ex.meta_robots, pc.x_robots_tag, ex.canonical, res.final_url, allowed)
        target.is_indexable = idx
        target.indexability_reason = reason
        target.status = "crawled"

        # duplicate content detection (exact body match)
        if ex.word_count > 0:
            dup = db.execute(
                select(PageContent.page_id).where(
                    PageContent.project_id == project.id,
                    PageContent.content_hash == ex.content_hash,
                    PageContent.page_id != target.id,
                ).limit(1)
            ).scalar_one_or_none()
            target.duplicate_of_id = dup

        # discovery from this page
        if s["follow_links"] and target.depth < s["max_depth"]:
            for link in ex.links:
                self._add_url(db, project, link, "pagination" if is_pagination_url(link) else "link", target.depth + 1, s)
        for rel in ("next", "prev"):
            if ex.pagination.get(rel):
                self._add_url(db, project, ex.pagination[rel], "pagination", target.depth, s)
        if s["follow_canonicals"] and ex.canonical:
            self._add_url(db, project, ex.canonical, "canonical", target.depth, s)

    def _brand_terms(self, db: Session, project: Project) -> list[str]:
        if project.id not in self._brand_cache:
            g = db.execute(
                select(GuidelineVersion).where(GuidelineVersion.project_id == project.id, GuidelineVersion.is_active)
            ).scalar_one_or_none()
            terms = [project.name]
            if g and g.brand_context.get("brand_name"):
                terms.append(g.brand_context["brand_name"])
            self._brand_cache[project.id] = [t for t in dict.fromkeys(terms) if t]
        return self._brand_cache[project.id]


def run_crawl_job(job_id: int, fetcher_transport=None) -> None:
    CrawlRunner(job_id, fetcher_transport).run()
