"""Text helpers shared by the audit, validator and duplicate detection."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

STOPWORDS = set(
    """a an and are as at be but by for from has have in into is it its of on or our that the their this to
    was were will with your you we us more how what why when where which who can all any about best new get
    de la le les des et en el los las y del un une und der die das mit für zu von""".split()
)

GENERIC_TITLES = {
    "home", "homepage", "home page", "untitled", "untitled document", "page", "index", "welcome", "default",
    "new page", "test", "blog", "products", "services", "about", "contact", "document",
}

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F1E6-\U0001F1FF\U00002600-\U000026FF]")
EM_DASH_RE = re.compile("[—―]")
EN_DASH_RE = re.compile("–")

# Approximate glyph widths (px) for Arial at Google SERP sizes; 20px for titles, 14px for descriptions.
_NARROW = set("ijlI.,;:'!|()[]{}ft1 ")
_WIDE = set("mwMWOQGDH@%&")


def norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str | None) -> list[str]:
    return [t for t in norm(text).split() if t]


def content_tokens(text: str | None) -> list[str]:
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 1]


def pixel_width(text: str, font_px: int = 20) -> int:
    total = 0.0
    for ch in text or "":
        if ch in _NARROW:
            total += 0.30
        elif ch in _WIDE:
            total += 0.85
        elif ch.isupper():
            total += 0.68
        else:
            total += 0.53
    return int(total * font_px)


def contains_term(text: str, term: str) -> bool:
    """Whole-word, case-insensitive phrase match (handles punctuation)."""
    if not term.strip():
        return False
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(p) for p in term.strip().split()) + r"(?!\w)"
    return re.search(pattern, text or "", flags=re.I) is not None


def count_term(text: str, term: str) -> int:
    if not term.strip():
        return 0
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(p) for p in term.strip().split()) + r"(?!\w)"
    return len(re.findall(pattern, text or "", flags=re.I))


def keyword_coverage(text: str, keyword: str) -> float:
    """Share of the keyword's content tokens present in text (0..1), allowing simple plural forms."""
    kt = content_tokens(keyword) or tokens(keyword)
    if not kt:
        return 0.0
    tt = set(tokens(text))
    hit = 0
    for k in kt:
        if k in tt or k.rstrip("s") in tt or (k + "s") in tt or (k + "es") in tt:
            hit += 1
    return hit / len(kt)


def stuffing_terms(text: str, threshold: int) -> list[str]:
    c = Counter(content_tokens(text))
    return [w for w, n in c.items() if n >= threshold]


def similarity(a: str, b: str) -> float:
    ta, tb = set(content_tokens(a)), set(content_tokens(b))
    if not ta or not tb:
        return 1.0 if norm(a) == norm(b) and norm(a) else 0.0
    jacc = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, norm(a), norm(b)).ratio()
    return max(jacc, seq * 0.95)


def all_caps_words(text: str) -> list[str]:
    return [w for w in re.findall(r"\b[A-Z]{4,}\b", text or "")]


def opening(text: str, n: int = 3) -> str:
    return " ".join(tokens(text)[:n])
