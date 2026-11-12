"""Website-wide duplicate metadata and keyword-overlap (potential cannibalisation) detection."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MetadataVersion, Page, PageAnalysis, PageContent
from app.seo import text as tx
from app.seo.rules import SiteIndex


def _groups(values: dict[int, str]) -> list[dict]:
    by: dict[str, list[int]] = defaultdict(list)
    for pid, v in values.items():
        if v and v.strip():
            by[tx.norm(v)].append(pid)
    return [
        {"value": values[ids[0]], "page_ids": sorted(ids), "count": len(ids)}
        for _k, ids in by.items() if len(ids) > 1
    ]


def _near_pairs(values: dict[int, str], kind: str, threshold: float) -> list[dict]:
    site = SiteIndex()
    for pid, v in values.items():
        if kind == "title":
            site.add(pid, v, None)
        else:
            site.add(pid, None, v)
    seen = set()
    pairs = []
    for pid, v in values.items():
        if not v:
            continue
        for other, sim in site.near(pid, v, kind, threshold):
            key = tuple(sorted((pid, other)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"page_ids": list(key), "similarity": sim, "values": [values[key[0]], values[key[1]]]})
    return sorted(pairs, key=lambda p: -p["similarity"])


def duplicate_report(db: Session, project_id: int, source: str = "existing") -> dict:
    pages = {
        p.id: p for p in db.execute(
            select(Page).where(Page.project_id == project_id, Page.status == "crawled", Page.is_indexable.is_(True))
        ).scalars()
    }
    titles: dict[int, str] = {}
    descs: dict[int, str] = {}
    if source == "existing":
        for pid, t, d in db.execute(
            select(PageContent.page_id, PageContent.title, PageContent.meta_description)
            .where(PageContent.project_id == project_id)
        ):
            if pid in pages:
                titles[pid] = t or ""
                descs[pid] = d or ""
    else:
        for mv in db.execute(
            select(MetadataVersion).where(MetadataVersion.project_id == project_id, MetadataVersion.is_current.is_(True))
        ).scalars():
            if mv.page_id in pages:
                titles[mv.page_id] = mv.title
                descs[mv.page_id] = mv.description

    analyses = db.execute(
        select(PageAnalysis).where(PageAnalysis.project_id == project_id, PageAnalysis.is_current.is_(True))
    ).scalars().all()
    by_kw: dict[str, list[PageAnalysis]] = defaultdict(list)
    for a in analyses:
        if a.page_id in pages and a.primary_keyword:
            by_kw[" ".join(sorted(tx.content_tokens(a.primary_keyword)))].append(a)
    overlaps = []
    for _k, group in by_kw.items():
        if len(group) < 2:
            continue
        intents = {a.search_intent for a in group}
        overlaps.append({
            "primary_keyword": group[0].primary_keyword,
            "page_ids": sorted(a.page_id for a in group),
            "page_types": sorted({a.page_type for a in group}),
            "same_intent": len(intents) == 1,
            "note": ("Pages share a primary keyword and search intent. This is a potential overlap to review, "
                     "not a confirmed cannibalisation issue.") if len(intents) == 1 else
                    "Pages share a primary keyword but serve different intents; likely fine, review if needed.",
        })
    url_of = {pid: p.url for pid, p in pages.items()}
    return {
        "source": source,
        "duplicate_titles": _groups(titles),
        "duplicate_descriptions": _groups(descs),
        "near_duplicate_titles": _near_pairs(titles, "title", 0.9),
        "near_duplicate_descriptions": _near_pairs(descs, "description", 0.85),
        "keyword_overlaps": overlaps,
        "urls": url_of,
    }
