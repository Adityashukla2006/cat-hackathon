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
