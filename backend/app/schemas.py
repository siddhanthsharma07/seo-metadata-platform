"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORM):
    id: int
    email: str
    full_name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --------------------------------------------------------------- projects
class CrawlSettings(BaseModel):
    max_urls: int = Field(default=500, ge=1, le=100_000)
    max_depth: int = Field(default=5, ge=0, le=50)
    concurrency: int = Field(default=4, ge=1, le=32)
    delay_ms: int = Field(default=500, ge=0, le=60_000)
    max_retries: int = Field(default=2, ge=0, le=5)
    respect_robots: bool = True
    use_sitemaps: bool = True
    follow_links: bool = True
    follow_canonicals: bool = True
    include_subdomains: bool = False
    allowed_hosts: list[str] = []
    render_js: Literal["never", "auto", "always"] = "auto"
    exclude_patterns: list[str] = []
    include_patterns: list[str] = []
    strip_query_params: list[str] = []
    ignore_query_strings: bool = False


class AISettings(BaseModel):
    provider: Literal["anthropic", "openai"] | None = None
    model: str | None = Field(default=None, max_length=100)
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_attempts: int = Field(default=3, ge=1, le=6)
    concurrency: int = Field(default=3, ge=1, le=10)
    min_words: int = Field(default=40, ge=0, le=1000)
    include_non_indexable: bool = False


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=3, max_length=2048)
    primary_market: str = Field(default="", max_length=100)
    language: str = Field(default="en", max_length=20)
    target_country: str = Field(default="", max_length=100)
    target_audience: str = Field(default="", max_length=5000)
    business_category: str = Field(default="", max_length=200)
    crawl_settings: CrawlSettings = CrawlSettings()
    ai_settings: AISettings = AISettings()


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    primary_market: str | None = None
    language: str | None = None
    target_country: str | None = None
    target_audience: str | None = None
    business_category: str | None = None
    crawl_settings: CrawlSettings | None = None
    ai_settings: AISettings | None = None


class ProjectOut(ORM):
    id: int
    name: str
    domain: str
    base_url: str
    primary_market: str
    language: str
    target_country: str
    target_audience: str
    business_category: str
    crawl_settings: dict
    ai_settings: dict
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------- guidelines
class KeywordIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    priority: Literal["high", "medium", "low"] = "medium"
    applies_to: str = Field(default="", max_length=300)


class GuidelineIn(BaseModel):
    brand_context: dict = {}
    seo_guidelines: dict = {}
    guardrails: dict = {}
    keywords: list[KeywordIn] = []
    custom_instructions: str = Field(default="", max_length=20_000)
    change_note: str = Field(default="", max_length=500)

    @field_validator("seo_guidelines")
    @classmethod
    def _lengths(cls, v: dict) -> dict:
        for lo, hi in (("title_min", "title_max"), ("description_min", "description_max")):
            if lo in v and hi in v and v[lo] is not None and v[hi] is not None:
                if int(v[lo]) < 1 or int(v[hi]) > 1000 or int(v[lo]) > int(v[hi]):
                    raise ValueError(f"{lo} must be >= 1 and <= {hi}")
        if v.get("brand_name_placement") and v["brand_name_placement"] not in ("end", "start", "none", "homepage_only", "auto"):
            raise ValueError("brand_name_placement must be one of end, start, none, homepage_only, auto")
        return v


class GuidelineOut(ORM):
    id: int
    project_id: int
    version: int
    is_active: bool
    brand_context: dict
    seo_guidelines: dict
    guardrails: dict
    keywords: list
    custom_instructions: str
    change_note: str
    created_at: datetime


# ----------------------------------------------------------------- crawls
class CrawlStartIn(BaseModel):
    settings: CrawlSettings | None = None


class CrawlJobOut(ORM):
    id: int
    project_id: int
    status: str
    settings: dict
    stats: dict
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class CrawlLogOut(ORM):
    id: int
    level: str
    message: str
    url: str | None
    created_at: datetime


class ManualUrlsIn(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50_000)


# -------------------------------------------------------------- review
class PageActionIn(BaseModel):
    action: Literal["approve_both", "approve_title", "approve_description", "reject", "reject_title",
                    "reject_description", "edit", "reset"]
    title: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=2000)
    note: str = Field(default="", max_length=2000)


class RegenerateIn(BaseModel):
    fields: Literal["both", "title", "description"] = "both"
    feedback: str = Field(default="", max_length=4000)


class BulkIn(BaseModel):
    page_ids: list[int] = Field(min_length=1, max_length=10_000)
    action: Literal["approve_both", "approve_title", "approve_description", "reject", "regenerate", "generate"]
    feedback: str = Field(default="", max_length=4000)
    fields: Literal["both", "title", "description"] = "both"


class AIJobIn(BaseModel):
    kind: Literal["analyze", "generate", "regenerate"]
    page_ids: list[int] | None = None
    force: bool = False
    include_non_indexable: bool | None = None
    fields: Literal["both", "title", "description"] = "both"
    feedback: str = Field(default="", max_length=4000)


class AIJobOut(ORM):
    id: int
    project_id: int
    kind: str
    status: str
    params: dict
    total: int
    processed: int
    failed: int
    skipped: int
    error: str | None
    log: list
    created_at: datetime
    finished_at: datetime | None


class CredentialIn(BaseModel):
    provider: Literal["anthropic", "openai"]
    api_key: str = Field(min_length=10, max_length=500)
