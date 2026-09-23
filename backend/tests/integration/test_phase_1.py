"""Phase 1: generated data trains the models, a prediction returns a valid range, and the
replay streams telemetry over the WebSocket in order."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app, get_demo_timeline
from app.replay import demo_context, get_demo, load_demo
from app.schemas import (
    ShadowTimeline,
    WsReplayStatus,
    WsShadowDelta,
    WsTelemetry,
    parse_ws_message,
)
from app.shadow.predictor import ShadowPredictor, get_predictor
from data.generate import DEMO_SCRIPT, SHIFT_MINUTES, generate
from ml.train import run


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase1")
    generate(seed=42, out_dir=root / "data")
    metrics = run(root / "data" / "history.csv", root / "models", seed=42)
    return {
        "metrics": metrics,
        "demo": load_demo(root / "data" / "demo_shift.json"),
        "predictor": ShadowPredictor.load(root / "models"),
    }


@pytest.fixture
def client(pg_engine, pipeline):
    app = create_app(pg_engine)
    predictor, demo = pipeline["predictor"], pipeline["demo"]
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_predictor] = lambda: predictor
    app.dependency_overrides[get_demo_timeline] = lambda: predictor.predict(demo_context(demo))
    with TestClient(app) as c:
        yield c


def test_models_train_on_generated_data(pipeline):
    duration = pipeline["metrics"]["duration"]
    assert duration["mae_p50"] < 0.6 * duration["mae_baseline_median"]
    assert 0.7 <= duration["coverage_p10_p90"] <= 0.9


def test_prediction_returns_valid_ranges(client, pipeline):
    ctx = demo_context(pipeline["demo"])
    response = client.post("/shadow/predict", json=ctx.model_dump())
    assert response.status_code == 200
    timeline = ShadowTimeline.model_validate(response.json())
    assert [t.seq for t in timeline.tasks] == [t.seq for t in ctx.tasks]
    for task in timeline.tasks:
        band = task.duration_min
        assert 0 < band.p10 <= band.p50 <= band.p90 < 240
        assert task.expected_fuel_l > 0
    assert timeline.total_min.p10 < SHIFT_MINUTES < timeline.total_min.p90 * 1.5
    assert client.get("/demo/shadow").json() == response.json()


def test_replay_streams_demo_telemetry_in_order(client, pipeline):
    with client.websocket_connect("/ws/telemetry?speed=1000000") as ws:
        messages = []
        while True:
            msg = parse_ws_message(ws.receive_text())
            messages.append(msg)
            if isinstance(msg, WsReplayStatus) and msg.state == "finished":
                break

    frames = [m.frame.model_dump() for m in messages if isinstance(m, WsTelemetry)]
    assert frames == pipeline["demo"]["telemetry"]
    minutes = [f["minute"] for f in frames]
    assert minutes == sorted(minutes) and minutes[-1] == SHIFT_MINUTES - 1

    # the scripted idle window shows up as the operator falling behind the shadow
    deltas = {m.minute: m.delta_min for m in messages if isinstance(m, WsShadowDelta)}
    idle_start, idle_end = DEMO_SCRIPT["idle_window"]
    assert deltas[idle_end] < deltas[idle_start - 1]
