"""Extract SEO metadata and meaningful visible content from HTML."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, Tag

from app.crawler.url_utils import normalize_url

BOILERPLATE_TAGS = ["script", "style", "noscript", "svg", "iframe", "template", "canvas", "form", "button", "select", "input", "dialog"]
STRUCTURAL_BOILERPLATE = ["nav", "footer", "header", "aside"]
BOILERPLATE_PATTERN = re.compile(
    r"(^|[\s_-])(cookie|consent|gdpr|banner|newsletter|subscribe|modal|popup|pop-up|breadcrumb|"
    r"menu|navbar|nav|sidebar|footer|header|share|social|skip-link|announcement|promo-bar|"
    r"related-posts|comments?|widget|advert|ads?|sponsor|toolbar|mega-menu|offcanvas|drawer)($|[\s_-])",
    re.I,
)
BOILERPLATE_ROLES = {"navigation", "banner", "contentinfo", "complementary", "search", "dialog", "alertdialog", "menu", "menubar"}

MAX_MAIN_CONTENT_CHARS = 60_000


@dataclass
class ExtractedPage:
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    meta_robots: str | None = None
    h1: list[str] = field(default_factory=list)
    h2: list[str] = field(default_factory=list)
    headings: list[dict] = field(default_factory=list)
    lang: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    word_count: int = 0
    intro: str = ""
    main_content: str = ""
    content_hash: str = ""
    links: list[str] = field(default_factory=list)
    pagination: dict = field(default_factory=dict)
    structured_data_types: list[str] = field(default_factory=list)
    entities: dict = field(default_factory=dict)
    heuristic_page_type: str | None = None
    looks_js_rendered: bool = False


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    return re.sub(r"\s+", " ", text).strip()


def _meta(soup: BeautifulSoup, *, name: str | None = None, prop: str | None = None) -> str | None:
    if name:
        el = soup.find("meta", attrs={"name": re.compile(rf"^{re.escape(name)}$", re.I)})
    else:
        el = soup.find("meta", attrs={"property": re.compile(rf"^{re.escape(prop or '')}$", re.I)})
    if el and el.get("content") is not None:
        return _clean(el.get("content"))
    return None


def _is_boilerplate(el: Tag) -> bool:
    if el.attrs is None:
        return False
    role = (el.get("role") or "").lower()
    if role in BOILERPLATE_ROLES:
        return True
    if el.get("aria-hidden") == "true" or el.has_attr("hidden"):
        return True
    style = (el.get("style") or "").replace(" ", "").lower()
    if "display:none" in style or "visibility:hidden" in style:
        return True
    ident = " ".join([el.get("id") or "", " ".join(el.get("class") or [])])
    if ident and BOILERPLATE_PATTERN.search(ident):
        # Avoid stripping the main container when the class merely contains "header"-like words
        if el.name in ("main", "article", "body"):
            return False
        return True
    return False


def _structured_data(soup: BeautifulSoup) -> tuple[list[str], list[str]]:
    types: list[str] = []
    product_names: list[str] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                t = item.get("@type")
                for tt in t if isinstance(t, list) else [t]:
                    if isinstance(tt, str):
                        types.append(tt)
                        if tt.lower() in ("product", "service", "softwareapplication") and isinstance(item.get("name"), str):
                            product_names.append(_clean(item["name"]) or "")
                if "@graph" in item:
                    stack.append(item["@graph"])
                for v in item.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
    return list(dict.fromkeys(types)), [p for p in dict.fromkeys(product_names) if p]


def guess_page_type(url: str, schema_types: list[str], h1: list[str], word_count: int, has_pagination: bool) -> str:
    path = urlsplit(url).path.lower().rstrip("/")
    st = {t.lower() for t in schema_types}
    if path in ("", "/") or re.fullmatch(r"/[a-z]{2}(-[a-z]{2})?", path):
        return "Homepage"
    if "product" in st or re.search(r"/(product|products|p|item|shop/[^/]+/[^/]+)/", path + "/"):
        return "Product"
    if st & {"article", "blogposting", "newsarticle"} or re.search(r"/(blog|news|article|articles|insights|stories|posts?)/.+", path):
        return "Blog/Article"
    if re.search(r"/(about|about-us|our-story|company|who-we-are)$", path):
        return "About Us"
    if re.search(r"/(contact|contact-us|support/contact)$", path):
        return "Contact Us"
    if re.search(r"/(locations?|stores?|branches|near-me|city)/", path + "/") or "localbusiness" in st:
        return "Location Page"
    if re.search(r"/(services?|solutions?)/", path + "/") or "service" in st:
        return "Service"
    if re.search(r"/(category|categories|collections?|c|shop|catalog)/", path + "/") or has_pagination or "collectionpage" in st:
        return "Category"
    if re.search(r"/(lp|landing|campaign|offers?|promo)/", path + "/"):
        return "Landing Page"
    if re.search(r"/(privacy|terms|legal|cookie|disclaimer|imprint)", path):
        return "Legal"
    if re.search(r"/(faq|faqs|help)", path) or "faqpage" in st:
        return "FAQ"
    return "Other"


def _brand_and_phrases(text: str, brand_terms: list[str]) -> dict:
    lower = text.lower()
    brand_mentions = {b: lower.count(b.lower()) for b in brand_terms if b and lower.count(b.lower())}
    # Frequent capitalised multi-word phrases (candidate entities / product names).
    phrases = re.findall(r"\b([A-Z][a-zA-Z0-9&'-]+(?:\s+[A-Z][a-zA-Z0-9&'-]+){1,3})\b", text)
    common = [p for p, c in Counter(phrases).most_common(15) if c >= 2]
    return {"brand_mentions": brand_mentions, "phrases": common}


def extract(html: str, url: str, brand_terms: list[str] | None = None, headers: dict | None = None) -> ExtractedPage:
    soup = BeautifulSoup(html, "lxml")
    out = ExtractedPage()

    head_title = soup.title.string if soup.title and soup.title.string else (soup.title.get_text() if soup.title else None)
    out.title = _clean(head_title) if head_title is not None else None
    out.meta_description = _meta(soup, name="description")
    out.meta_robots = _meta(soup, name="robots")
    out.og_title = _meta(soup, prop="og:title")
    out.og_description = _meta(soup, prop="og:description")
    canon = soup.find("link", rel=lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])])
    if canon and canon.get("href"):
        out.canonical = normalize_url(canon["href"], base=url) or canon["href"]
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        out.lang = html_tag.get("lang").strip()[:20]
    elif _meta(soup, name="language"):
        out.lang = _meta(soup, name="language")

    # pagination hints
    for rel in ("next", "prev"):
        el = soup.find("link", rel=lambda v, r=rel: v and r in [x.lower() for x in (v if isinstance(v, list) else [v])])
        if el and el.get("href"):
            out.pagination[rel] = normalize_url(el["href"], base=url)

    schema_types, product_names = _structured_data(soup)
    out.structured_data_types = schema_types

    # links (before stripping boilerplate: nav links are valid discovery sources)
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        rel = [r.lower() for r in (a.get("rel") or [])]
        if "nofollow" in rel:
            continue
        n = normalize_url(a["href"], base=url)
        if n:
            links.append(n)
    out.links = list(dict.fromkeys(links))

    # headings (full document, visible)
    for el in soup.find_all(["h1", "h2", "h3"]):
        t = _clean(el.get_text(" "))
        if t:
            out.headings.append({"level": int(el.name[1]), "text": t[:300]})
    out.h1 = [h["text"] for h in out.headings if h["level"] == 1]
    out.h2 = [h["text"] for h in out.headings if h["level"] == 2][:50]

    # ---- main content extraction
    body = soup.body or soup
    for c in body.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for tag in body.find_all(BOILERPLATE_TAGS):
        tag.decompose()
    main = body.find("main") or body.find(attrs={"role": "main"}) or body.find("article")
    container = main if isinstance(main, Tag) else body
    for tag in container.find_all(STRUCTURAL_BOILERPLATE):
        # keep <header> inside <article> (often contains H1/intro)
        if tag.name == "header" and tag.find_parent("article") is not None:
            continue
        tag.decompose()
    for tag in list(container.find_all(True)):
        if tag.attrs is not None and tag.parent is not None and _is_boilerplate(tag):
            tag.decompose()

    blocks: list[str] = []
    seen_blocks: set[str] = set()
    for el in container.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "blockquote", "dd", "dt", "figcaption"]):
        if el.find(["p", "li", "td"]) is not None and el.name in ("li", "td"):
            continue
        t = _clean(el.get_text(" "))
        if not t or len(t) < 3:
            continue
        key = t.lower()
        if key in seen_blocks:
            continue
        seen_blocks.add(key)
        blocks.append(t)
    if not blocks:
        t = _clean(container.get_text(" "))
        if t:
            blocks = [t]
    text = "\n".join(blocks)
    out.main_content = text[:MAX_MAIN_CONTENT_CHARS]
    out.word_count = len(re.findall(r"\w+", text))
    paras = [b for b in blocks if len(b) > 60 and b not in out.h1]
    out.intro = " ".join(paras[:2])[:600]
    out.content_hash = hashlib.sha256(re.sub(r"\s+", " ", text.lower()).encode("utf-8")).hexdigest()

    ents = _brand_and_phrases(text, brand_terms or [])
    ents["products"] = product_names
    out.entities = ents

    has_pagination = bool(out.pagination)
    out.heuristic_page_type = guess_page_type(url, schema_types, out.h1, out.word_count, has_pagination)

    raw_lower = html[:200_000].lower()
    out.looks_js_rendered = out.word_count < 80 and (
        'id="root"' in raw_lower or 'id="app"' in raw_lower or "__next" in raw_lower or "ng-version" in raw_lower
        or "data-reactroot" in raw_lower or raw_lower.count("<script") > 10
    )
    return out


def indexability(status: int | None, meta_robots: str | None, x_robots: str | None, canonical: str | None,
                 final_url: str, robots_allowed: bool) -> tuple[bool, str]:
    if status is None or not (200 <= status < 300):
        return False, f"HTTP {status}"
    if not robots_allowed:
        return False, "Blocked by robots.txt"
    directives = ",".join(filter(None, [meta_robots or "", x_robots or ""])).lower()
    if "noindex" in directives or "none" in [d.strip() for d in directives.split(",")]:
        return False, "noindex directive"
    if canonical:
        c = normalize_url(canonical)
        f = normalize_url(final_url)
        if c and f and c != f:
            return False, f"Canonicalised to {c}"
    return True, "Indexable"
