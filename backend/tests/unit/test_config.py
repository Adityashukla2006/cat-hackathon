import pytest

from app.config import Settings


def test_cors_origins_split_and_trimmed(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://a.test, http://b.test ,")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_api_key_is_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")
    settings = Settings(_env_file=None)
    assert "sk-test-value" not in repr(settings)
    assert settings.openai_api_key.get_secret_value() == "sk-test-value"


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@ep-x.neon.tech/db?sslmode=require",
        "postgresql://u:p@ep-x.neon.tech/db?sslmode=require",
        "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require",
    ],
)
def test_database_url_uses_psycopg_driver(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require"


def test_sqlite_url_is_left_alone(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    assert Settings(_env_file=None).database_url == "sqlite://"


def test_origin_allowed_by_list_or_regex(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://shadow-shift.vercel.app/")
    monkeypatch.setenv("FRONTEND_ORIGIN_REGEX", r"https://shadow-shift-[a-z0-9-]+\.vercel\.app")
    settings = Settings(_env_file=None)
    assert settings.origin_allowed("https://shadow-shift.vercel.app")
    assert settings.origin_allowed("https://shadow-shift-git-dev-team.vercel.app")
    assert not settings.origin_allowed("https://evil.example")
    assert not settings.origin_allowed("https://shadow-shift-x.vercel.app.evil.example")


def test_no_regex_means_list_only(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://shadow-shift.vercel.app")
    monkeypatch.delenv("FRONTEND_ORIGIN_REGEX", raising=False)
    settings = Settings(_env_file=None)
    assert not settings.origin_allowed("https://shadow-shift-preview.vercel.app")
