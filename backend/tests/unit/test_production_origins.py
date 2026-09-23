import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.db import make_engine
from app.main import create_app, get_demo_timeline
from app.replay import demo_context, get_demo
from app.schemas import WsReplayStatus, parse_ws_message
from app.shadow.predictor import get_predictor
from data.generate import generate

PROD = "https://shadow-shift.vercel.app"
PREVIEW = "https://shadow-shift-git-dev.vercel.app"


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


@pytest.fixture
def client(monkeypatch, demo, predictor):
    monkeypatch.setenv("FRONTEND_ORIGIN", PROD)
    monkeypatch.setenv("FRONTEND_ORIGIN_REGEX", r"https://shadow-shift-[a-z0-9-]+\.vercel\.app")
    get_settings.cache_clear()
    app = create_app(make_engine("sqlite://"))
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_predictor] = lambda: predictor
    app.dependency_overrides[get_demo_timeline] = lambda: predictor.predict(demo_context(demo))
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.mark.parametrize("origin", [PROD, PREVIEW])
def test_cors_allows_the_deployed_frontend(client, origin):
    response = client.get("/health", headers={"Origin": origin})
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_preflight_rejects_other_origins(client):
    response = client.options(
        "/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("origin", [PROD, PREVIEW])
def test_websocket_accepts_the_deployed_frontend(client, origin):
    with client.websocket_connect(
        "/ws/telemetry?speed=1000000&start=478", headers={"Origin": origin}
    ) as ws:
        messages = [parse_ws_message(ws.receive_text())]
        while not (isinstance(messages[-1], WsReplayStatus) and messages[-1].state == "finished"):
            messages.append(parse_ws_message(ws.receive_text()))
    assert messages[0] == WsReplayStatus(state="started", minute=478)


def test_websocket_rejects_other_origins(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws/telemetry", headers={"Origin": "https://evil.example"}
        ) as ws:
            ws.receive_text()
    assert exc.value.code == 1008
