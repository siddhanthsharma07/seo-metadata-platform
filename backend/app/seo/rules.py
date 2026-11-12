"""Deterministic metadata checks shared by the existing-metadata audit and proposal validation.

Each check returns issues of the form::

    {code, field, name, severity, explanation, recommendation, source: "rule", blocking}

``blocking`` marks violations of measurable mandatory requirements (guardrails, configured
length range, duplication). Blocking issues always fail validation and block approval.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.seo import text as tx
from app.seo.guidelines import ProjectContext

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
UNSUPPORTED_CLAIM_PATTERNS = [
    "#1", "no. 1", "number one", "best in the world", "world's best", "guaranteed", "guarantee",
    "100%", "cheapest", "lowest price", "free shipping", "risk-free", "award-winning", "certified",
    "clinically proven", "official", "lifetime warranty", "best price", "unbeatable",
]


@dataclass
class PageFacts:
    page_id: int
    url: str
    page_type: str = "Other"
    primary_keyword: str = ""
    secondary_keywords: list[str] = field(default_factory=list)
    h1: list[str] = field(default_factory=list)
    intro: str = ""
    content: str = ""
    usps: list[str] = field(default_factory=list)

    @property
    def is_homepage(self) -> bool:
        return self.page_type == "Homepage"


class SiteIndex:
    """Website-wide index of titles/descriptions for duplicate and near-duplicate checks."""

    def __init__(self):
        self.titles: dict[str, set[int]] = defaultdict(set)
        self.descs: dict[str, set[int]] = defaultdict(set)
        self.raw_titles: dict[int, str] = {}
        self.raw_descs: dict[int, str] = {}
        self.openings: dict[str, set[int]] = defaultdict(set)
        self.tok_index: dict[str, dict[str, set[int]]] = {"title": defaultdict(set), "description": defaultdict(set)}
        self.tok_sets: dict[str, dict[int, set[str]]] = {"title": {}, "description": {}}

    def add(self, page_id: int, title: str | None, desc: str | None):
        if title:
            self.titles[tx.norm(title)].add(page_id)
            self.raw_titles[page_id] = title
            self._index("title", page_id, title)
        if desc:
            self.descs[tx.norm(desc)].add(page_id)
            self.raw_descs[page_id] = desc
            self.openings[tx.opening(desc, 4)].add(page_id)
            self._index("description", page_id, desc)

    def _index(self, kind: str, page_id: int, value: str):
        toks = set(tx.content_tokens(value))
        self.tok_sets[kind][page_id] = toks
        for t in toks:
            self.tok_index[kind][t].add(page_id)

    def exact_title_dupes(self, page_id: int, title: str) -> set[int]:
        return self.titles.get(tx.norm(title), set()) - {page_id}

    def exact_desc_dupes(self, page_id: int, desc: str) -> set[int]:
        return self.descs.get(tx.norm(desc), set()) - {page_id}

    def near(self, page_id: int, value: str, kind: str, threshold: float) -> list[tuple[int, float]]:
        pool = self.raw_titles if kind == "title" else self.raw_descs
        n = tx.norm(value)
        vt = set(tx.content_tokens(value))
        if not vt:
            return []
        counts: dict[int, int] = defaultdict(int)
        for t in vt:
            for pid in self.tok_index[kind].get(t, ()):
                counts[pid] += 1
        out = []
        for pid, shared in counts.items():
            if pid == page_id:
                continue
            ot = self.tok_sets[kind].get(pid, set())
            if shared / max(1, min(len(vt), len(ot))) < 0.6:
                continue  # cheap prefilter via inverted index
            other = pool[pid]
            if tx.norm(other) == n:
                continue
            s = tx.similarity(value, other)
            if s >= threshold:
                out.append((pid, round(s, 2)))
        return sorted(out, key=lambda x: -x[1])[:5]

    def same_opening(self, page_id: int, desc: str) -> int:
        return len(self.openings.get(tx.opening(desc, 4), set()) - {page_id})


def _issue(code, field, name, severity, explanation, recommendation, blocking=False, **extra):
    d = {"code": code, "field": field, "name": name, "severity": severity, "explanation": explanation,
         "recommendation": recommendation, "source": "rule", "blocking": blocking}
    d.update(extra)
    return d


def check_title(title: str | None, ctx: ProjectContext, facts: PageFacts, site: SiteIndex | None, mode: str) -> list[dict]:
    """mode: 'audit' (existing metadata) or 'validate' (proposed metadata)."""
    issues: list[dict] = []
    strict = mode == "validate"
    tmin, tmax = ctx.title_range
    if not title or not title.strip():
        return [_issue("title_missing", "title", "Missing meta title", "Critical",
                       "The page has no <title> element or it is empty.",
                       "Add a unique, descriptive title that leads with the page's primary topic.", blocking=True)]
    t = title.strip()
    n = len(t)
    if n < tmin:
        sev = "High" if n < tmin - 15 else "Medium"
        issues.append(_issue("title_too_short", "title", "Title too short", sev,
                             f"Title is {n} characters; the configured target is {tmin}-{tmax}.",
                             "Add the primary keyword or a meaningful qualifier supported by the page content.",
                             blocking=strict))
    elif n > tmax:
        sev = "High" if n > tmax + 15 else "Medium"
        issues.append(_issue("title_too_long", "title", "Title too long", sev,
                             f"Title is {n} characters; the configured target is {tmin}-{tmax}.",
                             "Shorten the title and keep the most important words first.", blocking=strict))
    px = tx.pixel_width(t, 20)
    if px > 600:
        issues.append(_issue("title_truncation_risk", "title", "Truncation risk in search results", "Medium",
                             f"Estimated display width is ~{px}px; Google typically truncates titles around 580-600px.",
                             "Use shorter words or remove secondary qualifiers.", pixel_width=px))
    if tx.norm(t) in tx.GENERIC_TITLES or tx.norm(t) in {tx.norm(ctx.domain), tx.norm(ctx.brand_name)}:
        issues.append(_issue("title_generic", "title", "Generic or weak title", "High",
                             "The title does not describe what the page offers.",
                             "Describe the page's specific topic, product or service.", blocking=strict))

    # keyword
    kw = facts.primary_keyword.strip()
    if kw:
        cov = tx.keyword_coverage(t, kw)
        if cov == 0:
            issues.append(_issue("title_keyword_missing", "title", "Primary keyword missing from title", "High",
                                 f"The primary keyword '{kw}' does not appear in the title.",
                                 "Include the primary keyword naturally, ideally in the first half.", blocking=False))
        elif cov < 0.6:
            issues.append(_issue("title_keyword_partial", "title", "Primary keyword only partially present", "Low",
                                 f"Only part of '{kw}' appears in the title.",
                                 "Use the full keyword phrase if it reads naturally."))
        elif tx.contains_term(t, kw) and t.lower().find(kw.lower()) > len(t) * 0.6:
            issues.append(_issue("title_keyword_late", "title", "Primary keyword placed late", "Low",
                                 "The keyword appears near the end of the title, where it may be truncated.",
                                 "Move the primary keyword closer to the start."))
        if tx.count_term(t, kw) > 1:
            issues.append(_issue("title_keyword_repeated", "title", "Keyword repeated in title", "Medium",
                                 f"'{kw}' appears more than once in the title.", "Use the keyword once.", blocking=strict))
    stuffed = tx.stuffing_terms(t, 3)
    if stuffed:
        issues.append(_issue("title_keyword_stuffing", "title", "Keyword stuffing", "High",
                             f"Repeated terms: {', '.join(stuffed)}.", "Remove repetition; write for people first.",
                             blocking=True))

    # brand rules
    brand = ctx.brand_name
    placement = (ctx.seo.get("brand_name_placement") or "auto").lower()
    if brand:
        cnt = tx.count_term(t, brand)
        if cnt > 1:
            issues.append(_issue("title_brand_repeated", "title", "Brand name repeated", "Medium",
                                 f"'{brand}' appears {cnt} times in the title.", "Mention the brand once at most.",
                                 blocking=strict))
        has = cnt > 0
        if placement == "none" and has and not facts.is_homepage:
            issues.append(_issue("title_brand_prohibited", "title", "Brand name used against guidelines", "High",
                                 "Guidelines say titles must not include the brand name.", "Remove the brand name.",
                                 blocking=True))
        elif placement == "homepage_only" and has and not facts.is_homepage:
            issues.append(_issue("title_brand_prohibited", "title", "Brand name only allowed on homepage", "High",
                                 "Guidelines restrict the brand name to the homepage title.", "Remove the brand name.",
                                 blocking=True))
        elif placement in ("end", "start") and not has:
            issues.append(_issue("title_brand_missing", "title", "Brand name missing", "Medium",
                                 f"Guidelines place the brand name at the {placement} of titles.",
                                 f"Add '{brand}' at the {placement} of the title.", blocking=strict))
        elif placement == "end" and has and not tx.norm(t).endswith(tx.norm(brand)):
            issues.append(_issue("title_brand_position", "title", "Brand name in wrong position", "Low",
                                 "Guidelines place the brand name at the end of titles.",
                                 f"Move '{brand}' to the end, e.g. '... {ctx.seo.get('brand_separator', ' | ').strip()} {brand}'.",
                                 blocking=strict))
        elif placement == "start" and has and not tx.norm(t).startswith(tx.norm(brand)):
            issues.append(_issue("title_brand_position", "title", "Brand name in wrong position", "Low",
                                 "Guidelines place the brand name at the start of titles.", f"Start the title with '{brand}'.",
                                 blocking=strict))
        if has and brand not in t and brand.lower() in t.lower():
            issues.append(_issue("title_brand_casing", "title", "Brand name spelling/casing", "Medium",
                                 f"The brand must be written exactly as '{brand}'.", f"Write '{brand}'.", blocking=strict))

    # site-wide uniqueness
    if site is not None:
        dupes = site.exact_title_dupes(facts.page_id, t)
        if dupes:
            issues.append(_issue("title_duplicate", "title", "Duplicate title", "High",
                                 f"The same title is used on {len(dupes)} other page(s).",
                                 "Differentiate the title using what is unique about this page.", blocking=True,
                                 related_pages=sorted(dupes)[:20]))
        else:
            near = site.near(facts.page_id, t, "title", 0.9)
            if near:
                issues.append(_issue("title_near_duplicate", "title", "Near-duplicate title", "Medium",
                                     f"Very similar to {len(near)} other title(s).",
                                     "Make the title more specific to this page.", blocking=False,
                                     related_pages=[p for p, _ in near]))
    issues.extend(_guardrail_checks(t, "title", ctx, strict))
    return issues


def check_description(desc: str | None, ctx: ProjectContext, facts: PageFacts, site: SiteIndex | None, mode: str) -> list[dict]:
    issues: list[dict] = []
    strict = mode == "validate"
    dmin, dmax = ctx.description_range
    if not desc or not desc.strip():
        return [_issue("description_missing", "description", "Missing meta description", "High" if not strict else "Critical",
                       "The page has no meta description; search engines will generate a snippet from page text.",
                       "Write a description that summarises the page's purpose and value.", blocking=True)]
    d = desc.strip()
    n = len(d)
    if n < dmin:
        sev = "High" if n < dmin - 40 else "Medium"
        issues.append(_issue("description_too_short", "description", "Description too short", sev,
                             f"Description is {n} characters; the configured target is {dmin}-{dmax}.",
                             "Add useful, page-specific detail (what the visitor will find or can do).", blocking=strict))
    elif n > dmax:
        sev = "Medium" if n <= dmax + 40 else "High"
        issues.append(_issue("description_too_long", "description", "Description too long", sev,
                             f"Description is {n} characters; the configured target is {dmin}-{dmax}.",
                             "Tighten the copy so the key message is not truncated.", blocking=strict))
    kw = facts.primary_keyword.strip()
    if kw and tx.keyword_coverage(d, kw) < 0.6:
        issues.append(_issue("description_keyword_missing", "description", "Primary keyword missing", "Medium",
                             f"'{kw}' is not present in the description.", "Mention the primary topic naturally.",
                             blocking=False))
    if kw and tx.count_term(d, kw) > 2:
        issues.append(_issue("description_keyword_repeated", "description", "Keyword over-used", "Medium",
                             f"'{kw}' appears {tx.count_term(d, kw)} times.", "Use the keyword once or twice.",
                             blocking=strict))
    stuffed = tx.stuffing_terms(d, 4)
    if stuffed:
        issues.append(_issue("description_keyword_stuffing", "description", "Keyword stuffing", "High",
                             f"Repeated terms: {', '.join(stuffed)}.", "Rewrite in natural language.", blocking=True))
    if facts.secondary_keywords and not any(tx.keyword_coverage(d, s) >= 0.6 for s in facts.secondary_keywords):
        issues.append(_issue("description_secondary_missing", "description", "No secondary keyword", "Low",
                             "None of the secondary keywords appear in the description.",
                             "Integrate a relevant secondary keyword if it fits naturally."))
    found_claims = [c for c in UNSUPPORTED_CLAIM_PATTERNS if c in d.lower()]
    if found_claims:
        page_text = (facts.content + " " + facts.intro).lower()
        unsupported = [c for c in found_claims if c not in page_text]
        if unsupported:
            issues.append(_issue("description_unsupported_claim", "description", "Potentially unsupported claim", "High",
                                 f"Contains claim(s) not found in the page content: {', '.join(unsupported)}.",
                                 "Only state claims that the page itself supports.", blocking=strict))
    if site is not None:
        dupes = site.exact_desc_dupes(facts.page_id, d)
        if dupes:
            issues.append(_issue("description_duplicate", "description", "Duplicate description", "High",
                                 f"The same description is used on {len(dupes)} other page(s).",
                                 "Write a description specific to this page.", blocking=True, related_pages=sorted(dupes)[:20]))
        else:
            near = site.near(facts.page_id, d, "description", 0.85)
            if near:
                issues.append(_issue("description_near_duplicate", "description", "Near-duplicate description", "Medium",
                                     f"Very similar to {len(near)} other description(s).",
                                     "Differentiate using this page's specific content.", related_pages=[p for p, _ in near]))
            if strict and site.same_opening(facts.page_id, d) >= 2:
                issues.append(_issue("description_repetitive_opening", "description", "Repetitive opening", "Low",
                                     "Several other descriptions start with the same words.",
                                     "Vary the opening so snippets don't look templated."))
    issues.extend(_guardrail_checks(d, "description", ctx, strict))
    if ctx.guardrails.get("formatting", {}).get("no_pipes_in_description") and "|" in d:
        issues.append(_issue("format_pipe", "description", "Pipe character in description", "Medium",
                             "Guidelines prohibit '|' in descriptions.", "Use a full sentence instead.", blocking=True))
    return issues


def _guardrail_checks(value: str, field: str, ctx: ProjectContext, strict: bool) -> list[dict]:
    issues = []
    for w in ctx.list_rule("never_use_words"):
        if tx.contains_term(value, w):
            issues.append(_issue("guardrail_prohibited_word", field, "Prohibited word used", "Critical",
                                 f"'{w}' is on this website's never-use list.", f"Remove '{w}'.", blocking=True, term=w))
    for p in ctx.list_rule("prohibited_phrases"):
        if tx.contains_term(value, p) or p.lower() in value.lower():
            issues.append(_issue("guardrail_prohibited_phrase", field, "Prohibited phrase used", "Critical",
                                 f"'{p}' must not appear.", f"Remove '{p}'.", blocking=True, term=p))
    for c in ctx.list_rule("prohibited_claims"):
        if c.lower() in value.lower():
            issues.append(_issue("guardrail_prohibited_claim", field, "Prohibited claim", "Critical",
                                 f"The claim '{c}' must never be made.", "Remove the claim.", blocking=True, term=c))
    for comp in ctx.list_rule("competitor_brands"):
        if tx.contains_term(value, comp):
            issues.append(_issue("guardrail_competitor", field, "Competitor brand mentioned", "Critical",
                                 f"Competitor brand '{comp}' must not be used.", f"Remove '{comp}'.", blocking=True, term=comp))
    for w in ctx.list_rule("avoid_words"):
        if tx.contains_term(value, w):
            issues.append(_issue("guardrail_avoid_word", field, "Discouraged word used", "Low",
                                 f"'{w}' should be avoided for this website.", f"Consider replacing '{w}'.", term=w))
    fmt = ctx.guardrails.get("formatting", {}) or {}
    if fmt.get("no_em_dash") and (tx.EM_DASH_RE.search(value) or tx.EN_DASH_RE.search(value)):
        issues.append(_issue("format_em_dash", field, "Em/en dash used", "High",
                             "Guidelines prohibit em dashes.", "Replace with a comma, colon or pipe.", blocking=True))
    if fmt.get("no_exclamation") and "!" in value:
        issues.append(_issue("format_exclamation", field, "Exclamation mark used", "Medium",
                             "Guidelines prohibit exclamation marks.", "Remove the exclamation mark.", blocking=True))
    if fmt.get("no_emoji") and tx.EMOJI_RE.search(value):
        issues.append(_issue("format_emoji", field, "Emoji used", "Medium", "Guidelines prohibit emoji.",
                             "Remove emoji.", blocking=True))
    if fmt.get("no_all_caps"):
        caps = [w for w in tx.all_caps_words(value) if w.lower() != (ctx.brand_name or "").lower()]
        if caps:
            issues.append(_issue("format_all_caps", field, "All-caps words", "Low",
                                 f"All-caps words: {', '.join(caps[:5])}.", "Use sentence or title case unless it is an acronym."))
    if "  " in value or value != value.strip():
        issues.append(_issue("format_whitespace", field, "Extra whitespace", "Low", "Contains double or leading/trailing spaces.",
                             "Remove extra spaces.", blocking=strict))
    return issues


def check_pair(title: str | None, desc: str | None, ctx: ProjectContext, facts: PageFacts, site: SiteIndex | None,
               mode: str) -> list[dict]:
    issues = check_title(title, ctx, facts, site, mode) + check_description(desc, ctx, facts, site, mode)
    combined = f"{title or ''} {desc or ''}"
    missing = [w for w in ctx.list_rule("must_use_words") if not tx.contains_term(combined, w)]
    if missing and (title or desc):
        issues.append(_issue("guardrail_must_use_missing", "both", "Mandatory word missing", "High",
                             f"Must-use word(s) not present in title or description: {', '.join(missing)}.",
                             "Include the mandatory wording where it is accurate for the page.", blocking=mode == "validate",
                             terms=missing))
    if mode == "validate" and facts.primary_keyword and title and desc:
        if tx.keyword_coverage(combined, facts.primary_keyword) == 0:
            issues.append(_issue("keyword_absent_everywhere", "both", "Primary keyword absent", "High",
                                 "The primary keyword appears in neither the title nor the description.",
                                 "Use the primary keyword at least once.", blocking=True))
    issues.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))
    return issues
