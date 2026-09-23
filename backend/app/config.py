import re
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    database_url: str = "postgresql+psycopg://shadow:shadow@localhost:5433/shadow_shift"
    frontend_origin: str = "http://localhost:5173"
    # optional, e.g. Vercel preview deploys: https://shadow-shift-.*\.vercel\.app
    frontend_origin_regex: str | None = None

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        """Neon and Render hand out postgres:// URLs; SQLAlchemy needs the psycopg driver."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    def origin_allowed(self, origin: str) -> bool:
        if origin in self.cors_origins:
            return True
        return bool(self.frontend_origin_regex and re.fullmatch(self.frontend_origin_regex, origin))


@lru_cache
def get_settings() -> Settings:
    return Settings()
