"""Phase 4: the full demo shift runs with no errors on a production-configured backend.

Locally: Docker Postgres through a Neon-style postgresql:// URL, the deployed frontend's
origin on every request and on the WebSocket, and LLM outputs replayed from a recorded cache.
Against the real deploy: set DEPLOYED_API_URL (and DEPLOYED_FRONTEND_ORIGIN) to run the last
test; it is skipped otherwise. OpenAI is never called.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.agents.dispatcher import DispatchNote
from app.agents.drills import DrillContent
from app.agents.handover import HandoverText
from app.config import get_settings
from app.db import make_engine
from app.guides import get_guides
from app.llm import CachedLLM, FakeLLM, set_llm
from app.main import create_app, get_demo_timeline
from app.record_cache import run_demo
from app.replay import demo_context, get_demo, load_demo
from app.retrieval import GuideIndex, get_guide_index
from app.schemas import (
    AlertKind,
    Briefing,
    IncidentReport,
    Severity,
    WsAlert,
    WsIncidentLogged,
    WsReplan,
    WsReplayStatus,
    parse_ws_message,
)
from app.shadow.predictor import ShadowPredictor, get_predictor
from data.generate import DEMO_SCRIPT, generate
from ml.train import run

ORIGIN = "https://shadow-shift.vercel.app"
DEMO_SCHEMAS = {Briefing, DispatchNote, IncidentReport, DrillContent}

SCRIPTED = (
    FakeLLM()
    .on(Briefing, Briefing(headline="Wet haul ramp", key_risks=["soft edge"], focus_tip="Slow"))
    .on(DispatchNote, DispatchNote(explanation="Stockpile and yard first while fresh."))
    .on(
        IncidentReport,
        IncidentReport(
            category="ground",
            summary="Right track sank at the edge of the haul ramp.",
            severity=Severity.warning,
            hazard_kind="soft_ground",
            actions_taken=["backed off"],
        ),
    )
    .on(
        DrillContent,
        DrillContent(
            scenario="The ramp edge gives way.",
            question="What first?",
            options=["Stop and back off", "Keep digging", "Speed up"],
            answer=0,
            explanation="Stop, back off, and report it.",
        ),
    )
    .on(HandoverText, HandoverText(headline="Ramp soft", carry_over=[], watch_outs=[]))
)


def _drain(ws) -> list:
    messages = []
    while True:
        msg = parse_ws_message(ws.receive_text())
        messages.append(msg)
        if isinstance(msg, WsReplayStatus) and msg.state == "finished":
            return messages


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase4")
    generate(seed=42, out_dir=root / "data")
    run(root / "data" / "history.csv", root / "models", seed=42)
    demo = load_demo(root / "data" / "demo_shift.json")
    predictor = ShadowPredictor.load(root / "models")
    cache_path = root / "llm_cache.json"
    run_demo(CachedLLM(SCRIPTED, cache_path, record=True), demo, predictor)
    return demo, predictor, cache_path


@pytest.fixture
def production(monkeypatch, pg_engine, pipeline):
    demo, predictor, cache_path = pipeline
    neon_style = pg_engine.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    monkeypatch.setenv("DATABASE_URL", neon_style)
    monkeypatch.setenv("FRONTEND_ORIGIN", ORIGIN)
    get_settings.cache_clear()
    engine = make_engine(get_settings().database_url)

    live = FakeLLM()  # nothing registered: anything the cache misses falls back to templates
    set_llm(CachedLLM(live, cache_path))
    app = create_app(engine)
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_predictor] = lambda: predictor
    app.dependency_overrides[get_demo_timeline] = lambda: predictor.predict(demo_context(demo))
    index = GuideIndex([s for g in get_guides() for s in g.sections], llm=None)
    app.dependency_overrides[get_guide_index] = lambda: index
    headers = {"Origin": ORIGIN}
    with TestClient(app, headers=headers) as client:
        with client.websocket_connect("/ws/telemetry?speed=1000000", headers=headers) as ws:
            messages = _drain(ws)
        (alert, *_) = [m.alert for m in messages if isinstance(m, WsAlert)]
        shift_id = alert.shift_id
        responses = {
            path: client.get(path)
            for path in (
                "/health",
                "/demo/plan",
                "/hazards",
                f"/shifts/{shift_id}/alerts",
                f"/shifts/{shift_id}/incidents",
                f"/shifts/{shift_id}/drills",
                f"/shifts/{shift_id}/handover",
                "/operators/1/coach",
                "/training/modules?operator_id=1",
            )
        }
        responses["/chat"] = client.post("/chat", json={"message": "How do I check the tracks?"})
    yield {"messages": messages, "responses": responses, "live": live}
    engine.dispose()
    get_settings.cache_clear()


def test_database_url_is_normalized_for_psycopg(production):
    assert get_settings().database_url.startswith("postgresql+psycopg://")
    assert production["responses"]["/health"].json() == {"status": "ok", "database": True}


def test_every_frontend_endpoint_answers_for_the_deployed_origin(production):
    for path, response in production["responses"].items():
        assert response.status_code == 200, path
        assert response.headers["access-control-allow-origin"] == ORIGIN, path


def test_full_demo_shift_streams_the_scripted_events(production):
    messages = production["messages"]
    assert messages[0] == WsReplayStatus(state="started", minute=0)
    assert messages[-1] == WsReplayStatus(state="finished", minute=479)
    kinds = [m.alert.kind for m in messages if isinstance(m, WsAlert)]
    assert AlertKind.seatbelt in kinds and AlertKind.idle_deviation in kinds
    assert len([m for m in messages if isinstance(m, WsReplan)]) == 1
    (incident,) = [m.incident for m in messages if isinstance(m, WsIncidentLogged)]
    assert incident.minute == DEMO_SCRIPT["incident_minute"]


def test_demo_llm_outputs_come_from_the_cache(production):
    reached = {c["schema"] for c in production["live"].calls if c["method"] == "structured"}
    assert reached.isdisjoint(DEMO_SCHEMAS)
    plan = production["responses"]["/demo/plan"].json()
    assert plan["briefing_source"] == "llm"
    assert plan["briefing"]["headline"] == "Wet haul ramp"
    (replan,) = [m.replan for m in production["messages"] if isinstance(m, WsReplan)]
    assert replan.explanation == "Stockpile and yard first while fresh."
    drills = production["responses"][f"/shifts/{_shift_id(production)}/drills"].json()
    assert drills and all(d["scenario"] == "The ramp edge gives way." for d in drills)


def _shift_id(production) -> int:
    return next(m.alert.shift_id for m in production["messages"] if isinstance(m, WsAlert))


DEPLOYED = os.environ.get("DEPLOYED_API_URL")


@pytest.mark.skipif(not DEPLOYED, reason="set DEPLOYED_API_URL to check the deployed backend")
def test_deployed_backend_runs_the_full_demo_shift():
    import httpx
    from websockets.sync.client import connect

    base = DEPLOYED.rstrip("/")
    assert httpx.get(f"{base}/health", timeout=90).json() == {"status": "ok", "database": True}
    assert httpx.get(f"{base}/demo/plan", timeout=90).status_code == 200

    url = base.replace("http", "ws", 1) + "/ws/telemetry?speed=1000000"
    messages = []
    with connect(url, origin=os.environ.get("DEPLOYED_FRONTEND_ORIGIN"), open_timeout=90) as ws:
        while not (messages and getattr(messages[-1], "state", None) == "finished"):
            messages.append(parse_ws_message(ws.recv(timeout=120)))
    kinds = {m.alert.kind for m in messages if isinstance(m, WsAlert)}
    assert {AlertKind.seatbelt, AlertKind.idle_deviation} <= kinds
