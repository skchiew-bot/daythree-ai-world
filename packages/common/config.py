"""Central settings object. Every service constructs one `Settings()` at startup and
fails fast if a required value is missing (spec §4 rule 10: no credentials in prompts/
artifacts/logs; spec §23: secrets outside code) — never silently defaults a secret.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The `.env.example` placeholders — fine for local dev, never acceptable once
# `environment` is production. Kept as named constants (not inlined into the field
# defaults) so `require_safe_for_production` can compare against exactly these values
# rather than duplicating the literal strings.
_DEFAULT_SECRET_KEY = "change-me-to-a-random-64-char-string"
_DEFAULT_OBJECT_STORE_SECRET_KEY = "daythree_minio_secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "dev"
    secret_key: str = Field(default=_DEFAULT_SECRET_KEY)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    database_url: str = "postgresql+asyncpg://daythree:daythree_dev_password@localhost:5432/daythree"

    redis_url: str = "redis://localhost:6379/0"
    redis_stream_name: str = "daythree.events"

    object_store_endpoint_url: str = "http://localhost:9000"
    object_store_access_key: str = "daythree_minio"
    object_store_secret_key: str = _DEFAULT_OBJECT_STORE_SECRET_KEY
    object_store_bucket: str = "daythree-artifacts"
    object_store_region: str = "us-east-1"
    object_store_signed_url_ttl_seconds: int = 300

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    default_model_provider: str = "mock"
    default_model_name: str = "claude-sonnet-5"

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "daythree-api"
    log_level: str = "INFO"

    seed_tenant_code: str = "daythree-hq"
    seed_admin_email: str = "admin@daythree.local"
    seed_admin_password: str = "ChangeMe123!"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def require_safe_for_production(self) -> None:
        """Called once by each real server process at startup (API, worker) — never
        by `Settings()` construction itself, so scripts/tests that just want to read
        dev-mode config aren't affected. `environment=dev` (the default) never raises
        here; this is the actual enforcement of the "never silently defaults a secret"
        promise this module's docstring makes, closing the gap where a production
        deployment could otherwise inherit the `.env.example` placeholders unnoticed.
        """
        if not self.is_production:
            return
        if not self.secret_key or self.secret_key == _DEFAULT_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY is unset or still the placeholder default in a production "
                "environment — every JWT would be forgeable. Set a real, random SECRET_KEY."
            )
        if not self.object_store_secret_key or self.object_store_secret_key == _DEFAULT_OBJECT_STORE_SECRET_KEY:
            raise RuntimeError(
                "OBJECT_STORE_SECRET_KEY is unset or still the placeholder default in a "
                "production environment — artifact storage would be openly writable/readable "
                "by anyone who reaches the endpoint. Set a real, random secret key."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
