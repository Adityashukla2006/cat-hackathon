from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _service() -> dict:
    (service,) = yaml.safe_load((ROOT / "render.yaml").read_text())["services"]
    return service


def test_render_builds_data_and_models_from_seed_42():
    service = _service()
    assert service["rootDir"] == "backend"
    build = service["buildCommand"]
    assert "pip install -r requirements.txt" in build
    assert "data/generate.py --seed 42" in build
    assert "ml/train.py --seed 42" in build
    assert build.index("generate.py") < build.index("train.py")


def test_render_serves_the_app_on_the_render_port():
    service = _service()
    assert "app.main:app" in service["startCommand"]
    assert "--port $PORT" in service["startCommand"]
    assert "--proxy-headers" in service["startCommand"]
    assert service["healthCheckPath"] == "/health"


def test_render_secrets_are_set_in_the_dashboard_not_the_file():
    env = {e["key"]: e for e in _service()["envVars"]}
    for key in ("OPENAI_API_KEY", "DATABASE_URL", "FRONTEND_ORIGIN"):
        assert env[key] == {"key": key, "sync": False}
    assert env["PYTHON_VERSION"]["value"].startswith("3.11")


def test_render_env_vars_are_documented_in_env_example():
    documented = {
        line.split("=", 1)[0]
        for line in (ROOT / ".env.example").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    }
    keys = {e["key"] for e in _service()["envVars"]} - {"PYTHON_VERSION"}
    assert keys <= documented
