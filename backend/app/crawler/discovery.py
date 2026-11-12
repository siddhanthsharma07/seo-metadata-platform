"""robots.txt handling and XML sitemap / sitemap-index discovery."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from lxml import etree

from app.crawler.fetcher import Fetcher

log = logging.getLogger(__name__)


@dataclass
class RobotsInfo:
    url: str
    status: int | None
    parser: RobotFileParser | None
    sitemaps: list[str] = field(default_factory=list)
    crawl_delay: float | None = None
    error: str | None = None

    def allowed(self, url: str, user_agent: str) -> bool:
        if self.parser is None:
            return True
        # RobotFileParser falls back to the "*" group when no group matches our agent.
        return self.parser.can_fetch(user_agent, url)


async def load_robots(fetcher: Fetcher, base_url: str, user_agent: str) -> RobotsInfo:
    parts = urlsplit(base_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    res = await fetcher.fetch(robots_url)
    info = RobotsInfo(url=robots_url, status=res.status, parser=None)
    if res.error and res.status is None:
        info.error = res.error
        return info
    if res.status and 400 <= res.status < 500:
        # Per RFC 9309: 4xx => no restrictions.
        return info
    if res.status and res.status >= 500:
        # Server error => treat as complete disallow (conservative, per RFC 9309).
        rp = RobotFileParser()
        rp.parse(["User-agent: *", "Disallow: /"])
        info.parser = rp
        info.error = f"robots.txt returned {res.status}; crawling is paused for safety"
        return info
    rp = RobotFileParser()
    lines = res.text.splitlines()
    rp.parse(lines)
    info.parser = rp
    for line in lines:
        if line.lower().startswith("sitemap:"):
            sm = line.split(":", 1)[1].strip()
            if sm:
                info.sitemaps.append(urljoin(robots_url, sm))
    try:
        cd = rp.crawl_delay(user_agent)
        info.crawl_delay = float(cd) if cd is not None else None
    except Exception:  # noqa: BLE001
        pass
    return info


@dataclass
class SitemapResult:
    urls: list[str] = field(default_factory=list)
    sitemaps_read: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_sitemap_xml(text: str) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemaps) for a urlset or sitemapindex document."""
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False)
        root = etree.fromstring(text.encode("utf-8"), parser=parser)
    except (etree.XMLSyntaxError, ValueError):
        return [], []
    if root is None:
        return [], []
    tag = etree.QName(root).localname.lower()
    locs = [
        (el.text or "").strip()
        for el in root.iter()
        if isinstance(el.tag, str) and etree.QName(el).localname.lower() == "loc"
    ]
    locs = [loc for loc in locs if loc]
    if tag == "sitemapindex":
        return [], locs
    return locs, []


async def discover_sitemaps(
    fetcher: Fetcher, start_sitemaps: list[str], max_urls: int, max_sitemaps: int = 200
) -> SitemapResult:
    result = SitemapResult()
    queue = list(dict.fromkeys(start_sitemaps))
    seen: set[str] = set()
    while queue and len(result.sitemaps_read) < max_sitemaps and len(result.urls) < max_urls:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        res = await fetcher.fetch_text(sm)
        if not res.ok:
            result.errors.append(f"{sm}: {res.error or res.status}")
            continue
        result.sitemaps_read.append(sm)
        pages, children = parse_sitemap_xml(res.text)
        for child in children:
            if child not in seen:
                queue.append(urljoin(sm, child))
        for p in pages:
            result.urls.append(urljoin(sm, p))
            if len(result.urls) >= max_urls:
                break
    return result
