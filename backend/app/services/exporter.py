"""Excel (openpyxl) and CSV exports. Values are written in full (no truncation)."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditResult, MetadataVersion, Page, PageAnalysis, PageContent, Project
from app.seo.duplicates import duplicate_report

EXPORT_TYPES = {
    "complete_audit": "Complete Metadata Audit",
    "approved": "Approved Metadata Only",
    "needs_improvement": "Pages Requiring Improvement",
    "missing": "Missing Metadata Report",
    "duplicates": "Duplicate Metadata Report",
    "crawl_errors": "Crawl Errors Report",
}

IMPROVEMENT_THRESHOLD = 70


def _rows_for_pages(db: Session, project_id: int) -> list[dict]:
    pages = db.execute(select(Page).where(Page.project_id == project_id).order_by(Page.id)).scalars().all()
    contents = {c.page_id: c for c in db.execute(select(PageContent).where(PageContent.project_id == project_id)).scalars()}
    analyses = {a.page_id: a for a in db.execute(select(PageAnalysis).where(PageAnalysis.project_id == project_id, PageAnalysis.is_current.is_(True))).scalars()}
    proposals = {m.page_id: m for m in db.execute(select(MetadataVersion).where(MetadataVersion.project_id == project_id, MetadataVersion.is_current.is_(True))).scalars()}
    audits = {}
    for a in db.execute(select(AuditResult).where(AuditResult.project_id == project_id, AuditResult.is_current.is_(True))).scalars():
        audits[(a.page_id, a.target)] = a
    rows = []
    for i, p in enumerate(pages, 1):
        c = contents.get(p.id)
        an = analyses.get(p.id)
        mv = proposals.get(p.id)
        ea = audits.get((p.id, "existing"))
        pa = audits.get((p.id, "proposed"))
        rows.append({
            "page": p, "content": c, "analysis": an, "proposal": mv, "existing_audit": ea, "proposed_audit": pa,
            "S. No.": i,
            "Page URL": p.url,
            "Status": p.status,
            "HTTP Status": p.http_status,
            "Indexable": "Yes" if p.is_indexable else ("No" if p.is_indexable is False else ""),
            "Indexability Reason": p.indexability_reason or "",
            "Page Type": (an.page_type if an else (c.heuristic_page_type if c else "")) or "",
            "Primary Keyword": an.primary_keyword if an else "",
            "Secondary Keywords": ", ".join(an.secondary_keywords) if an else "",
            "Search Intent": an.search_intent if an else "",
            "H1": " | ".join(c.h1) if c else "",
            "Canonical URL": (c.canonical or "") if c else "",
            "Meta Robots": (c.meta_robots or "") if c else "",
            "Word Count": c.word_count if c else "",
            "Existing Meta Title": (c.title or "") if c else "",
            "Existing Title Characters": len(c.title or "") if c else 0,
            "Proposed Meta Title": mv.title if mv else "",
            "Proposed Title Characters": len(mv.title) if mv else 0,
            "Existing Meta Description": (c.meta_description or "") if c else "",
            "Existing Description Characters": len(c.meta_description or "") if c else 0,
            "Proposed Meta Description": mv.description if mv else "",
            "Proposed Description Characters": len(mv.description) if mv else 0,
            "Existing Title Score": ea.title_score if ea else "",
            "Existing Description Score": ea.description_score if ea else "",
            "Existing Metadata Score": ea.overall_score if ea else "",
            "Proposed Metadata Score": pa.overall_score if pa else "",
            "Issues Identified": "; ".join(f"[{i['severity']}] {i['name']}" for i in (ea.issues if ea else [])),
            "Proposal Source": mv.source if mv else "",
            "Validation Status": mv.validation_status if mv else "",
            "Validation Notes": mv.validation_summary if mv else "",
            "Title Approval": p.title_status,
            "Description Approval": p.description_status,
            "Approved Meta Title": p.approved_title if p.title_status == "approved" else "",
            "Approved Meta Description": p.approved_description if p.description_status == "approved" else "",
            "Approved At": p.approved_at.isoformat() if p.approved_at else "",
            "Error": p.error or "",
            "Final URL": p.final_url or "",
            "Discovered Via": p.source,
        })
    return rows


AUDIT_COLUMNS = [
    "S. No.", "Page URL", "Page Type", "Primary Keyword", "Existing Meta Title", "Existing Title Characters",
    "Proposed Meta Title", "Proposed Title Characters", "Existing Meta Description", "Existing Description Characters",
    "Proposed Meta Description", "Proposed Description Characters", "Existing Metadata Score", "Proposed Metadata Score",
    "Issues Identified", "Validation Status", "Title Approval", "Description Approval", "Secondary Keywords",
    "Search Intent", "H1", "HTTP Status", "Indexable", "Indexability Reason", "Canonical URL", "Meta Robots",
    "Word Count", "Existing Title Score", "Existing Description Score", "Proposal Source", "Validation Notes",
]


def build_sheets(db: Session, project_id: int, export_type: str) -> list[tuple[str, list[str], list[list]]]:
    if export_type not in EXPORT_TYPES:
        raise ValueError(f"Unknown export type '{export_type}'")
    rows = _rows_for_pages(db, project_id)
    crawled = [r for r in rows if r["page"].status == "crawled"]

    def table(rs, cols):
        return [[r.get(c, "") for c in cols] for r in rs]

    if export_type == "complete_audit":
        sheets = [("Metadata Audit", AUDIT_COLUMNS, table(crawled, AUDIT_COLUMNS))]
        issue_cols = ["Page URL", "Target", "Field", "Issue", "Severity", "Explanation", "Recommendation", "Source"]
        issue_rows = []
        for r in crawled:
            for target, audit in (("Existing", r["existing_audit"]), ("Proposed", r["proposed_audit"])):
                for i in (audit.issues if audit else []):
                    issue_rows.append([r["Page URL"], target, i.get("field"), i.get("name"), i.get("severity"),
                                       i.get("explanation"), i.get("recommendation"), i.get("source")])
        sheets.append(("Issues", issue_cols, issue_rows))
        err_cols = ["Page URL", "Status", "HTTP Status", "Error", "Final URL", "Discovered Via"]
        sheets.append(("Crawl Errors", err_cols, table([r for r in rows if r["page"].status in ("failed", "blocked", "redirected", "skipped", "duplicate")], err_cols)))
        return sheets
    if export_type == "approved":
        cols = ["S. No.", "Page URL", "Page Type", "Primary Keyword", "Approved Meta Title", "Approved Title Characters",
                "Approved Meta Description", "Approved Description Characters", "Existing Meta Title", "Existing Meta Description",
                "Approved At"]
        out = []
        for n, r in enumerate([r for r in crawled if r["page"].title_status == "approved" or r["page"].description_status == "approved"], 1):
            r = {**r, "S. No.": n, "Approved Title Characters": len(r["Approved Meta Title"]),
                 "Approved Description Characters": len(r["Approved Meta Description"])}
            out.append([r.get(c, "") for c in cols])
        return [("Approved Metadata", cols, out)]
    if export_type == "needs_improvement":
        cols = ["Page URL", "Page Type", "Primary Keyword", "Existing Meta Title", "Existing Title Characters",
                "Existing Meta Description", "Existing Description Characters", "Existing Metadata Score", "Issues Identified",
                "Proposed Meta Title", "Proposed Meta Description", "Proposed Metadata Score"]
        sel = [r for r in crawled if r["existing_audit"] and (r["existing_audit"].overall_score < IMPROVEMENT_THRESHOLD
                                                            or r["existing_audit"].critical_count or r["existing_audit"].high_count)]
        return [("Requires Improvement", cols, table(sel, cols))]
    if export_type == "missing":
        cols = ["Page URL", "Page Type", "Indexable", "Missing", "Existing Meta Title", "Existing Meta Description", "H1"]
        out = []
        for r in crawled:
            miss = [n for n, v in (("Title", r["Existing Meta Title"]), ("Description", r["Existing Meta Description"])) if not v]
            if miss:
                out.append([r["Page URL"], r["Page Type"], r["Indexable"], " & ".join(miss), r["Existing Meta Title"],
                            r["Existing Meta Description"], r["H1"]])
        return [("Missing Metadata", cols, out)]
    if export_type == "duplicates":
        sheets = []
        for source in ("existing", "proposed"):
            rep = duplicate_report(db, project_id, source)
            urls = rep["urls"]
            cols = ["Type", "Group", "Shared Value", "Page URL", "Similarity"]
            out = []
            g = 0
            for kind, key in (("Duplicate title", "duplicate_titles"), ("Duplicate description", "duplicate_descriptions")):
                for grp in rep[key]:
                    g += 1
                    for pid in grp["page_ids"]:
                        out.append([kind, g, grp["value"], urls.get(pid, pid), 1.0])
            for kind, key in (("Near-duplicate title", "near_duplicate_titles"), ("Near-duplicate description", "near_duplicate_descriptions")):
                for pair in rep[key]:
                    g += 1
                    for pid, val in zip(pair["page_ids"], pair["values"]):
                        out.append([kind, g, val, urls.get(pid, pid), pair["similarity"]])
            for ov in rep["keyword_overlaps"]:
                g += 1
                for pid in ov["page_ids"]:
                    out.append(["Keyword overlap (review)", g, ov["primary_keyword"], urls.get(pid, pid), ov["note"]])
            sheets.append((f"{source.title()} Metadata", cols, out))
        return sheets
    if export_type == "crawl_errors":
        cols = ["Page URL", "Status", "HTTP Status", "Error", "Final URL", "Discovered Via", "Indexability Reason"]
        sel = [r for r in rows if r["page"].status in ("failed", "blocked", "skipped", "duplicate", "redirected")
               or (r["page"].http_status and r["page"].http_status >= 400)]
        return [("Crawl Errors", cols, table(sel, cols))]
    return []


def to_xlsx(project: Project, export_type: str, sheets) -> bytes:
    wb = Workbook()
    ws0 = wb.active
    ws0.title = "Summary"
    ws0.append(["SEO Metadata Intelligence Platform"])
    ws0["A1"].font = Font(bold=True, size=14)
    for row in (["Report", EXPORT_TYPES[export_type]], ["Website", project.name], ["Domain", project.domain],
                ["Generated (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")],
                ["Note", "Scores are an internal quality assessment and do not guarantee rankings or CTR."]):
        ws0.append(row)
    for name, _cols, data in sheets:
        ws0.append([f"Rows in '{name}'", len(data)])
    ws0.column_dimensions["A"].width = 26
    ws0.column_dimensions["B"].width = 80
    header_fill = PatternFill("solid", fgColor="1F2937")
    for name, cols, data in sheets:
        ws = wb.create_sheet(title=name[:31])
        ws.append(cols)
        for r in data:
            ws.append([("" if v is None else v) for v in r])
            for c in ws[ws.max_row]:
                if isinstance(c.value, str) and c.value.startswith("="):
                    c.data_type = "s"  # store as text, never as a formula
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = header_fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = "B2" if len(cols) > 3 else "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(1, len(data) + 1)}"
        for idx, col in enumerate(cols, 1):
            longest = max([len(str(col))] + [len(str(r[idx - 1])) for r in data[:500]])
            ws.column_dimensions[get_column_letter(idx)].width = max(10, min(70, longest + 2))
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, str) and len(c.value) > 60:
                    c.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv_safe(v):
    if v is None:
        return ""
    if isinstance(v, str) and v[:1] in ("=", "+", "@", "\t", "\r"):
        return "'" + v  # neutralise spreadsheet formula injection
    return v


def to_csv(sheets) -> bytes:
    """CSV of the first (primary) sheet. UTF-8 with BOM so Excel opens non-ASCII text correctly."""
    _name, cols, data = sheets[0]
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    w.writerow(cols)
    for r in data:
        w.writerow([_csv_safe(v) for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")
