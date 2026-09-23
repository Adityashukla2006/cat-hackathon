import pytest
from fastapi.testclient import TestClient

from app.db import make_engine
from app.main import create_app, get_demo_timeline
from app.replay import demo_context, get_demo
from app.schemas import WsReplayStatus, WsTelemetry, parse_ws_message
from data.generate import generate


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


@pytest.fixture
def client(demo, predictor):
    app = create_app(make_engine("sqlite://"))
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_demo_timeline] = lambda: predictor.predict(demo_context(demo))
    with TestClient(app) as c:
        yield c


def _next_telemetry(ws) -> WsTelemetry:
    while True:
        msg = parse_ws_message(ws.receive_text())
        if isinstance(msg, WsTelemetry):
            return msg


def _until_finished(ws) -> WsReplayStatus:
    while True:
        msg = parse_ws_message(ws.receive_text())
        if isinstance(msg, WsReplayStatus) and msg.state == "finished":
            return msg


def test_second_screen_joins_the_running_replay(client):
    with client.websocket_connect("/ws/telemetry?speed=300") as tablet:
        assert parse_ws_message(tablet.receive_text()) == WsReplayStatus(state="started", minute=0)
        for _ in range(6):
            _next_telemetry(tablet)
        with client.websocket_connect("/ws/telemetry?speed=300") as console:
            joined = _next_telemetry(console)
            assert joined.frame.minute > 0  # mid-stream, no restart
            tablet.send_json({"action": "stop"})
            finished_console = _until_finished(console)
        finished_tablet = _until_finished(tablet)
    assert finished_console == finished_tablet
    assert finished_tablet.minute < 479


def test_a_new_client_restarts_a_finished_replay(client):
    with client.websocket_connect("/ws/telemetry?speed=1000000&start=470") as ws:
        _until_finished(ws)
    with client.websocket_connect("/ws/telemetry?speed=1000000&start=475") as ws:
        assert parse_ws_message(ws.receive_text()).state == "started"
        assert _next_telemetry(ws).frame.minute == 475


def test_disconnecting_one_client_keeps_the_replay_running(client):
    hub = client.app.state.hub
    with client.websocket_connect("/ws/telemetry?speed=300") as ws:
        _next_telemetry(ws)
    assert hub.running
    hub.control("stop")
