"""Guideline defaults and an immutable, per-project view used by audit/validation/AI stages."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GuidelineVersion, Project

PAGE_TYPES = [
    "Homepage", "Category", "Subcategory", "Product", "Service", "Blog/Article", "Landing Page",
    "Location Page", "About Us", "Contact Us", "FAQ", "Legal", "Other",
]

DEFAULT_BRAND_CONTEXT = {
    "brand_name": "",
    "brand_category": "",
    "positioning": "",
    "target_audience": "",
    "target_geography": "",
    "tone_of_voice": "",
    "communication_style": "",
    "terminology": "",
}

DEFAULT_SEO_GUIDELINES = {
    "primary_keyword_rules": "Use the page's primary keyword naturally, ideally near the start of the title.",
    "secondary_keyword_rules": "Integrate one or two secondary keywords naturally in the description where relevant.",
    "brand_name_placement": "end",  # end | start | none | homepage_only | auto
    "brand_separator": " | ",
    "title_min": 50,
    "title_max": 60,
    "description_min": 140,
    "description_max": 160,
    "keyword_frequency": "Primary keyword at most once in the title and at most twice in the description.",
    "page_type_rules": {
        "Homepage": "",
        "Category": "",
        "Product": "",
        "Blog/Article": "",
        "Service": "",
        "Landing Page": "",
        "Location Page": "",
    },
    "internal_linking_rules": "",
    "product_naming_rules": "",
}

DEFAULT_GUARDRAILS = {
    "must_use_words": [],
    "never_use_words": [],
    "avoid_words": [],
    "prohibited_phrases": [],
    "prohibited_claims": [],
    "competitor_brands": [],
    "formatting": {
        "no_em_dash": False,
        "no_exclamation": False,
        "no_all_caps": True,
        "no_emoji": True,
        "no_pipes_in_description": False,
    },
    "formatting_notes": "",
    "country_language_rules": "",
    "brand_naming_restrictions": "",
}


def merge_defaults(defaults: dict, value: dict | None) -> dict:
    out = json.loads(json.dumps(defaults))
    for k, v in (value or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def _clean_list(values) -> list[str]:
    if isinstance(values, str):
        values = [v for v in values.replace("\n", ",").split(",")]
    return [str(v).strip() for v in (values or []) if str(v).strip()]


@dataclass(frozen=True)
class ProjectContext:
    """Everything the audit, validators and AI stages may know about ONE website."""

    project_id: int
    project_name: str
    domain: str
    language: str
    target_country: str
    primary_market: str
    target_audience: str
    business_category: str
    guideline_version_id: int | None
    guideline_version: int | None
    brand: dict
    seo: dict
    guardrails: dict
    keywords: list = field(default_factory=list)
    custom_instructions: str = ""

    @property
    def brand_name(self) -> str:
        return (self.brand.get("brand_name") or "").strip()

    @property
    def title_range(self) -> tuple[int, int]:
        return int(self.seo.get("title_min") or 50), int(self.seo.get("title_max") or 60)

    @property
    def description_range(self) -> tuple[int, int]:
        return int(self.seo.get("description_min") or 140), int(self.seo.get("description_max") or 160)

    def list_rule(self, key: str) -> list[str]:
        return _clean_list(self.guardrails.get(key))

    def fingerprint(self) -> str:
        payload = json.dumps(
            {"v": self.guideline_version_id, "b": self.brand, "s": self.seo, "g": self.guardrails,
             "k": self.keywords, "c": self.custom_instructions, "lang": self.language, "country": self.target_country},
            sort_keys=True, default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def active_guideline(db: Session, project_id: int) -> GuidelineVersion | None:
    return db.execute(
        select(GuidelineVersion)
        .where(GuidelineVersion.project_id == project_id, GuidelineVersion.is_active.is_(True))
        .order_by(GuidelineVersion.version.desc())
    ).scalars().first()


def build_context(db: Session, project: Project) -> ProjectContext:
    g = active_guideline(db, project.id)
    guard = merge_defaults(DEFAULT_GUARDRAILS, g.guardrails if g else None)
    for key in ("must_use_words", "never_use_words", "avoid_words", "prohibited_phrases", "prohibited_claims", "competitor_brands"):
        guard[key] = _clean_list(guard.get(key))
    keywords = []
    for k in (g.keywords if g else []) or []:
        if isinstance(k, dict) and str(k.get("keyword", "")).strip():
            keywords.append({
                "keyword": str(k["keyword"]).strip(),
                "priority": k.get("priority", "medium"),
                "applies_to": str(k.get("applies_to", "") or "").strip(),
            })
    brand = merge_defaults(DEFAULT_BRAND_CONTEXT, g.brand_context if g else None)
    if not brand.get("brand_name"):
        brand["brand_name"] = project.name
    return ProjectContext(
        project_id=project.id,
        project_name=project.name,
        domain=project.domain,
        language=project.language or "en",
        target_country=project.target_country or "",
        primary_market=project.primary_market or "",
        target_audience=project.target_audience or "",
        business_category=project.business_category or "",
        guideline_version_id=g.id if g else None,
        guideline_version=g.version if g else None,
        brand=brand,
        seo=merge_defaults(DEFAULT_SEO_GUIDELINES, g.seo_guidelines if g else None),
        guardrails=guard,
        keywords=keywords,
        custom_instructions=(g.custom_instructions if g else "") or "",
    )
