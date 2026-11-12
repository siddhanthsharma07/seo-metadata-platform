"""SQLAlchemy ORM models.

Every project-scoped table carries ``project_id`` and every query in the API layer is
filtered by it, so one website's context, guidelines and data never leak into another.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# --------------------------------------------------------------------------- users


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    hashed_password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProviderCredential(TimestampMixin, Base):
    """API keys entered in the Settings UI, encrypted at rest (Fernet)."""

    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    encrypted_key: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(16), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ------------------------------------------------------------------------ projects


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(253))
    base_url: Mapped[str] = mapped_column(String(2048))
    primary_market: Mapped[str] = mapped_column(String(100), default="")
    language: Mapped[str] = mapped_column(String(20), default="en")
    target_country: Mapped[str] = mapped_column(String(100), default="")
    target_audience: Mapped[str] = mapped_column(Text, default="")
    business_category: Mapped[str] = mapped_column(String(200), default="")
    crawl_settings: Mapped[dict] = mapped_column(JSONType, default=dict)
    ai_settings: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    guidelines: Mapped[list[GuidelineVersion]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class GuidelineVersion(TimestampMixin, Base):
    """Versioned Brand SEO Intelligence configuration for exactly one project.

    Sections: brand_context (A), seo_guidelines (B), guardrails (C), custom_instructions (D),
    keywords (mandatory keywords with priorities).
    """

    __tablename__ = "guideline_versions"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    brand_context: Mapped[dict] = mapped_column(JSONType, default=dict)
    seo_guidelines: Mapped[dict] = mapped_column(JSONType, default=dict)
    guardrails: Mapped[dict] = mapped_column(JSONType, default=dict)
    keywords: Mapped[list] = mapped_column(JSONType, default=list)
    custom_instructions: Mapped[str] = mapped_column(Text, default="")
    change_note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    project: Mapped[Project] = relationship(back_populates="guidelines")


# -------------------------------------------------------------------------- crawling


class CrawlJob(TimestampMixin, Base):
    __tablename__ = "crawl_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # pending | running | paused | stopping | stopped | completed | failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)
    stats: Mapped[dict] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    run_token: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CrawlLog(TimestampMixin, Base):
    __tablename__ = "crawl_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    crawl_job_id: Mapped[int] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class Page(TimestampMixin, Base):
    """A discovered URL (crawl frontier + crawl result + review state)."""

    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("project_id", "url"),
        Index("ix_pages_project_status", "project_id", "status"),
        Index("ix_pages_project_variation", "project_id", "variation_key"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    crawl_job_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="SET NULL"), nullable=True)
    url: Mapped[str] = mapped_column(String(2048))
    variation_key: Mapped[str] = mapped_column(String(2048))
    source: Mapped[str] = mapped_column(String(30), default="link")  # sitemap|link|manual|upload|canonical|seed|redirect|pagination
    depth: Mapped[int] = mapped_column(Integer, default=0)
    # queued | fetching | crawled | failed | blocked | skipped | duplicate
    status: Mapped[str] = mapped_column(String(20), default="queued")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    redirect_chain: Mapped[list] = mapped_column(JSONType, default=list)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    rendered_with_js: Mapped[bool] = mapped_column(Boolean, default=False)
    response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"), nullable=True)
    is_indexable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    indexability_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Review / approval state
    title_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    description_status: Mapped[str] = mapped_column(String(20), default="pending")
    approved_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    content: Mapped[PageContent | None] = relationship(back_populates="page", uselist=False, cascade="all, delete-orphan")


class PageContent(TimestampMixin, Base):
    """Existing SEO metadata + cleaned content extracted from the page."""

    __tablename__ = "page_contents"
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), unique=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    meta_robots: Mapped[str | None] = mapped_column(String(300), nullable=True)
    x_robots_tag: Mapped[str | None] = mapped_column(String(300), nullable=True)
    h1: Mapped[list] = mapped_column(JSONType, default=list)
    h2: Mapped[list] = mapped_column(JSONType, default=list)
    headings: Mapped[list] = mapped_column(JSONType, default=list)  # [{level, text}]
    lang: Mapped[str | None] = mapped_column(String(20), nullable=True)
    og_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    og_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    intro: Mapped[str] = mapped_column(Text, default="")
    main_content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    structured_data_types: Mapped[list] = mapped_column(JSONType, default=list)
    entities: Mapped[dict] = mapped_column(JSONType, default=dict)  # products, brand_mentions, phrases
    pagination: Mapped[dict] = mapped_column(JSONType, default=dict)
    heuristic_page_type: Mapped[str | None] = mapped_column(String(40), nullable=True)

    page: Mapped[Page] = relationship(back_populates="content")


# ---------------------------------------------------------------------------- AI + audit


class PageAnalysis(TimestampMixin, Base):
    """AI page understanding (stage 1)."""

    __tablename__ = "page_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    page_type: Mapped[str] = mapped_column(String(40))
    primary_topic: Mapped[str] = mapped_column(Text, default="")
    search_intent: Mapped[str] = mapped_column(String(40), default="")
    target_audience: Mapped[str] = mapped_column(Text, default="")
    primary_keyword: Mapped[str] = mapped_column(String(300), default="")
    secondary_keywords: Mapped[list] = mapped_column(JSONType, default=list)
    entities: Mapped[list] = mapped_column(JSONType, default=list)
    usps: Mapped[list] = mapped_column(JSONType, default=list)
    key_message: Mapped[str] = mapped_column(Text, default="")
    positioning: Mapped[str] = mapped_column(Text, default="")
    content_relevance: Mapped[str] = mapped_column(Text, default="")
    content_sufficient: Mapped[bool] = mapped_column(Boolean, default=True)
    insufficiency_reason: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(100), default="")


class AuditResult(TimestampMixin, Base):
    """Scores + issues for either existing metadata or a proposed metadata version."""

    __tablename__ = "audit_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    target: Mapped[str] = mapped_column(String(20), default="existing")  # existing | proposed
    metadata_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("metadata_versions.id", ondelete="CASCADE"), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    title_score: Mapped[int] = mapped_column(Integer, default=0)
    description_score: Mapped[int] = mapped_column(Integer, default=0)
    overall_score: Mapped[int] = mapped_column(Integer, default=0)
    breakdown: Mapped[dict] = mapped_column(JSONType, default=dict)
    issues: Mapped[list] = mapped_column(JSONType, default=list)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_evaluated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_summary: Mapped[str] = mapped_column(Text, default="")


class MetadataVersion(TimestampMixin, Base):
    """Every proposed title/description (AI generated, regenerated or manually edited)."""

    __tablename__ = "metadata_versions"
    __table_args__ = (UniqueConstraint("page_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="ai_generated")  # ai_generated|ai_regenerated|manual_edit
    # pending | passed | failed | needs_review
    validation_status: Mapped[str] = mapped_column(String(20), default="pending")
    validation_summary: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    rationale: Mapped[str] = mapped_column(Text, default="")
    feedback: Mapped[str] = mapped_column(Text, default="")
    guideline_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("guideline_versions.id", ondelete="SET NULL"), nullable=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ValidationResult(TimestampMixin, Base):
    __tablename__ = "validation_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    metadata_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("metadata_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    deterministic_issues: Mapped[list] = mapped_column(JSONType, default=list)
    ai_review: Mapped[dict] = mapped_column(JSONType, default=dict)


class ApprovalEvent(TimestampMixin, Base):
    __tablename__ = "approval_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    field: Mapped[str] = mapped_column(String(20), default="both")
    metadata_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("metadata_versions.id", ondelete="SET NULL"), nullable=True
    )
    value_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class AIJob(TimestampMixin, Base):
    __tablename__ = "ai_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # analyze | generate | regenerate | dedupe
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|completed|failed|cancelled
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[list] = mapped_column(JSONType, default=list)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AIUsageLog(TimestampMixin, Base):
    __tablename__ = "ai_usage_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"), nullable=True)
    stage: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExportRecord(TimestampMixin, Base):
    __tablename__ = "export_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    export_type: Mapped[str] = mapped_column(String(40))
    file_format: Mapped[str] = mapped_column(String(10))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    filename: Mapped[str] = mapped_column(String(300))


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
