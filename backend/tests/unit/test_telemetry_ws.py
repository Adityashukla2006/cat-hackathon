import pytest
from fastapi.testclient import TestClient

from app.db import make_engine
from app.main import create_app, get_demo_timeline
from app.replay import demo_context, get_demo
from app.schemas import TelemetryFrame, WsReplayStatus, WsShadowDelta, WsTelemetry, parse_ws_message
from app.shadow.predictor import get_predictor
from app.shadow.tracker import ShadowTracker
from data.generate import DEMO_FIRST_TASK_MINUTE, generate

FAST = 1_000_000  # replay speed that makes the sleep negligible


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


@pytest.fixture
def client(demo, predictor):
    app = create_app(make_engine("sqlite://"))
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_predictor] = lambda: predictor
    app.dependency_overrides[get_demo_timeline] = lambda: predictor.predict(demo_context(demo))
    with TestClient(app) as c:
        yield c


def _drain(ws) -> list:
    messages = []
    while True:
        msg = parse_ws_message(ws.receive_text())
        messages.append(msg)
        if isinstance(msg, WsReplayStatus) and msg.state == "finished":
            return messages


def test_streams_whole_shift_in_order_with_deltas(client):
    with client.websocket_connect(f"/ws/telemetry?speed={FAST}") as ws:
        messages = _drain(ws)
    assert messages[0] == WsReplayStatus(state="started", minute=0)
    frames = [m.frame for m in messages if isinstance(m, WsTelemetry)]
    assert len(frames) == 960
    assert [(f.minute, f.machine_id) for f in frames] == sorted(
        (f.minute, f.machine_id) for f in frames
    )
    deltas = [m for m in messages if isinstance(m, WsShadowDelta)]
    assert deltas[0].minute == DEMO_FIRST_TASK_MINUTE
    assert deltas[0].delta_min == pytest.approx(-DEMO_FIRST_TASK_MINUTE)
    assert messages[-1].minute == 479


def test_start_query_skips_ahead(client):
    with client.websocket_connect(f"/ws/telemetry?speed={FAST}&start=470") as ws:
        messages = _drain(ws)
    frames = [m.frame for m in messages if isinstance(m, WsTelemetry)]
    assert frames[0].minute == 470 and len(frames) == 20


def test_stop_control_ends_stream_early(client):
    with client.websocket_connect("/ws/telemetry?speed=600") as ws:
        ws.receive_text()
        ws.send_json({"action": "stop"})
        messages = _drain(ws)
    assert messages[-1].minute < 479


def test_demo_shadow_endpoint(client):
    response = client.get("/demo/shadow")
    assert response.status_code == 200
    assert [t["seq"] for t in response.json()["tasks"]] == list(range(1, 9))


def test_tracker_ignores_other_machines_and_prestart(predictor, demo):
    timeline = predictor.predict(demo_context(demo))
    tracker = ShadowTracker(timeline, machine_id=1)
    frame = TelemetryFrame.model_validate(demo["telemetry"][0])
    assert tracker.update(frame) is None  # minute 0, no task yet
    other = frame.model_copy(update={"machine_id": 2, "task_seq": 1})
    assert tracker.update(other) is None
    first = frame.model_copy(update={"minute": 10, "task_seq": 1})
    tracker.update(first.model_copy(update={"minute": 7}))
    assert tracker.update(first) == pytest.approx(-7)
