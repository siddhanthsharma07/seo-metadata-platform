"""Application settings, loaded from environment variables (see .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SEO Metadata Intelligence Platform"
    environment: str = "development"

    database_url: str = "postgresql+psycopg://seo:seo@localhost:5432/seo_metadata"
    redis_url: str = "redis://localhost:6379/0"

    # "celery" (production) or "inline" (runs background jobs in a thread; dev/tests only)
    task_backend: str = "celery"

    # Security
    secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    access_token_expire_minutes: int = 60 * 12
    allow_registration: bool = True
    cors_origins: str = "http://localhost:3000"

    # Crawler
    crawler_user_agent: str = "SEOMetadataIntelligenceBot/1.0 (+metadata audit; respects robots.txt)"
    crawler_timeout_seconds: float = 20.0
    crawler_max_bytes: int = 5_000_000
    # SSRF guard: only disable in local test environments.
    allow_private_networks: bool = False
    playwright_chromium_path: str | None = None

    # AI providers (keys may also be stored encrypted via the Settings UI)
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    default_ai_provider: str = "anthropic"
    default_anthropic_model: str = "claude-opus-5-5"
    default_openai_model: str = "gpt-5"
    ai_request_timeout_seconds: float = 180.0

    export_dir: str = "./exports"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
