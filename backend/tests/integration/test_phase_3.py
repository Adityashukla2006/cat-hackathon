"""Phase 3: a hazard logged by one machine warns the second machine on approach, the chatbot
answers a question using live shift data, and the Coach recommends a module that matches the
operator's recorded behavior. Docker Postgres, OpenAI mocked."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.assistant import shift_status
from app.db import HazardPin, make_session_factory
from app.guides import get_guides
from app.main import create_app, get_demo_timeline
from app.replay import demo_context, get_demo, load_demo
from app.retrieval import GuideIndex, get_guide_index
from app.schemas import (
    ChatAnswer,
    WsHazardPin,
    WsHazardWarning,
    WsReplayStatus,
    WsTelemetry,
    parse_ws_message,
)
from app.shadow.predictor import ShadowPredictor, get_predictor
from data.generate import DEMO_SCRIPT, generate
from ml.train import run


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase3")
    generate(seed=42, out_dir=root / "data")
    run(root / "data" / "history.csv", root / "models", seed=42)
    return load_demo(root / "data" / "demo_shift.json"), ShadowPredictor.load(root / "models")


@pytest.fixture
def client(pg_engine, pipeline):
    demo, predictor = pipeline
    app = create_app(pg_engine)
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_predictor] = lambda: predictor
    app.dependency_overrides[get_demo_timeline] = lambda: predictor.predict(demo_context(demo))
    index = GuideIndex([s for g in get_guides() for s in g.sections], llm=None)
    app.dependency_overrides[get_guide_index] = lambda: index
    with TestClient(app) as c:
        yield c


def _full_replay(client) -> list:
    messages = []
    with client.websocket_connect("/ws/telemetry?speed=1000000") as ws:
        while True:
            msg = parse_ws_message(ws.receive_text())
            messages.append(msg)
            if isinstance(msg, WsReplayStatus) and msg.state == "finished":
                return messages


def test_hazard_from_one_machine_warns_the_other_on_approach(client, pg_engine):
    messages = _full_replay(client)
    minute = None
    pin_minute, warnings = None, []
    for msg in messages:
        if isinstance(msg, WsTelemetry):
            minute = msg.frame.minute
        elif isinstance(msg, WsHazardPin) and msg.created:
            pin_minute = minute
            pin = msg.pin
        elif isinstance(msg, WsHazardWarning):
            warnings.append((minute, msg))

    assert pin_minute == DEMO_SCRIPT["incident_minute"]
    assert pin.reported_by_machine_id == 1 and pin.kind == "soft_ground"
    ((warn_minute, warning),) = warnings
    lo, hi = DEMO_SCRIPT["second_machine_approach"]
    assert warning.machine_id == 2 and lo <= warn_minute <= hi
    assert warning.pin.id == pin.id
    assert warning.distance_m > pin.radius_m

    db = make_session_factory(pg_engine)()
    stored = db.scalars(select(HazardPin)).one()
    assert (stored.id, stored.active, stored.reported_by_machine_id) == (pin.id, True, 1)
    db.close()
    hazards = client.get("/hazards").json()
    assert [h["id"] for h in hazards] == [pin.id]


def test_chatbot_answers_from_live_shift_data(client, fake_llm):
    with client.websocket_connect("/ws/telemetry?speed=3000") as ws:
        while True:
            msg = parse_ws_message(ws.receive_text())
            if isinstance(msg, WsTelemetry) and msg.frame.minute >= 250:
                ws.send_json({"action": "pause"})
                break
        hub = client.app.state.hub
        deadline = time.monotonic() + 5
        while not hub.replay.paused:
            assert time.monotonic() < deadline, "replay did not pause"
            time.sleep(0.01)
        status = shift_status(hub.runtime.session)
        assert status["current_task"] == "Build stockpile from pit spoil"

        # fallback path: the answer is built straight from live data
        fallback = client.post("/chat", json={"message": "How far behind am I?"}).json()
        behind = abs(round(status["minutes_vs_shadow"]))
        assert "Build stockpile from pit spoil" in fallback["answer"]
        assert f"{behind} min behind" in fallback["answer"]

        # LLM path: the model sees the same live data in its prompt
        def reply(system, user):
            live = json.loads(user.split("\n\nOPERATOR_QUESTION")[0])["LIVE_SHIFT"]
            return ChatAnswer(answer=f"You're on {live['current_task']}.")

        fake_llm.on(ChatAnswer, reply)
        answer = client.post("/chat", json={"message": "What am I working on?"}).json()
        assert answer["answer"] == "You're on Build stockpile from pit spoil."
        ws.send_json({"action": "stop"})


def test_coach_recommends_modules_matching_recorded_behavior(client):
    _full_replay(client)
    advice = client.get("/operators/1/coach").json()
    picks = {r["lesson_id"]: r for r in advice["recommendations"]}
    assert {"seatbelt", "soft-ground"} <= set(picks)
    assert "seatbelt unbuckled" in picks["seatbelt"]["reasons"][0]
    assert picks["soft-ground"]["reasons"][0].startswith("reported: ")
    assert advice["suggest_instructor"] in picks
