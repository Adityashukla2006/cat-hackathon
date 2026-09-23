"""Phase 2: replaying the demo shift triggers the seatbelt prompt, the idle deviation alert,
a replan, and a stored incident report at the scripted minutes. OpenAI is mocked."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.dispatcher import DispatchNote
from app.db import Alert, Incident, make_session_factory
from app.main import create_app, get_demo_timeline
from app.replay import demo_context, get_demo, load_demo
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
from data.generate import DEMO_EXECUTION_ORDER, DEMO_SCRIPT, generate
from ml.train import run

CANNED_REPORT = IncidentReport(
    category="ground",
    summary="Right track sank at the edge of the haul ramp.",
    severity=Severity.warning,
    hazard_kind="soft_ground",
    actions_taken=["backed off", "stopped work there"],
)


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase2")
    generate(seed=42, out_dir=root / "data")
    run(root / "data" / "history.csv", root / "models", seed=42)
    return load_demo(root / "data" / "demo_shift.json"), ShadowPredictor.load(root / "models")


@pytest.fixture
def replay(pg_engine, pipeline, fake_llm):
    demo, predictor = pipeline
    fake_llm.on(IncidentReport, CANNED_REPORT)
    fake_llm.on(DispatchNote, DispatchNote(explanation="Stockpile and yard first while fresh."))
    fake_llm.on(Briefing, Briefing(headline="Ramp ditch", key_risks=["wet"], focus_tip="Go slow"))

    app = create_app(pg_engine)
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_predictor] = lambda: predictor
    app.dependency_overrides[get_demo_timeline] = lambda: predictor.predict(demo_context(demo))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry?speed=1000000") as ws:
            messages = []
            while True:
                msg = parse_ws_message(ws.receive_text())
                messages.append(msg)
                if isinstance(msg, WsReplayStatus) and msg.state == "finished":
                    break
        plan = client.get("/demo/plan").json()
    db = make_session_factory(pg_engine)()
    yield {"messages": messages, "db": db, "fake_llm": fake_llm, "plan": plan}
    db.close()


def _alerts(messages, kind):
    return [m.alert for m in messages if isinstance(m, WsAlert) and m.alert.kind == kind]


def test_seatbelt_prompt_at_scripted_minute(replay):
    (alert,) = _alerts(replay["messages"], AlertKind.seatbelt)
    lo, hi = DEMO_SCRIPT["seatbelt_unbuckled"]
    assert lo <= alert.minute <= hi
    assert alert.severity == Severity.critical


def test_idle_deviation_alert_in_the_idle_window(replay):
    (alert,) = _alerts(replay["messages"], AlertKind.idle_deviation)
    lo, hi = DEMO_SCRIPT["idle_window"]
    assert lo <= alert.minute <= hi


def test_replan_follows_the_idle_deviation(replay):
    replans = [m for m in replay["messages"] if isinstance(m, WsReplan)]
    assert len(replans) == 1
    (idle,) = _alerts(replay["messages"], AlertKind.idle_deviation)
    assert replans[0].minute == idle.minute
    assert replans[0].replan.new_order == DEMO_EXECUTION_ORDER
    assert replans[0].replan.explanation == "Stockpile and yard first while fresh."


def test_incident_report_is_stored_at_the_scripted_minute(replay):
    (logged,) = [m.incident for m in replay["messages"] if isinstance(m, WsIncidentLogged)]
    assert logged.minute == DEMO_SCRIPT["incident_minute"]
    assert logged.report == CANNED_REPORT
    stored = replay["db"].scalars(select(Incident)).one()
    assert stored.minute == DEMO_SCRIPT["incident_minute"]
    assert stored.transcript == DEMO_SCRIPT["incident_transcript"]
    assert stored.report["hazard_kind"] == "soft_ground"
    assert stored.lat is not None and stored.lon is not None


def test_alerts_are_persisted_in_postgres(replay):
    streamed = [m.alert.id for m in replay["messages"] if isinstance(m, WsAlert)]
    stored = replay["db"].scalars(select(Alert).order_by(Alert.minute, Alert.id)).all()
    assert [a.id for a in stored] == streamed
    kinds = [a.kind for a in stored]
    assert kinds[:2] == ["seatbelt", "idle_deviation"]
    fatigue = [a for a in stored if a.kind == "fatigue"]
    assert len(fatigue) == 1 and fatigue[0].minute >= DEMO_SCRIPT["fatigue_from_minute"]


def test_llm_only_used_through_the_mocked_wrapper(replay):
    schemas = {c["schema"] for c in replay["fake_llm"].calls if c["method"] == "structured"}
    assert schemas == {IncidentReport, DispatchNote, Briefing}
    assert replay["plan"]["briefing"]["headline"] == "Ramp ditch"
