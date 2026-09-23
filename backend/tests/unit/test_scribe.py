from collections import defaultdict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.scribe import SYSTEM_PROMPT, fallback_report, scribe_node, write_report
from app.db import Incident, make_engine, make_session_factory
from app.graph import build_graph, run_event
from app.main import create_app, get_demo_timeline
from app.replay import demo_context, demo_frames, get_demo
from app.runtime import ShiftRuntime, seed_demo_shift
from app.schemas import IncidentReport, Severity, WsIncidentLogged, parse_ws_message
from app.shadow.predictor import get_predictor
from data.generate import DEMO_SCRIPT, generate

DEMO_NOTE = DEMO_SCRIPT["incident_transcript"]
LLM_REPORT = IncidentReport(
    category="ground",
    summary="Right track sank at the haul ramp edge.",
    severity="warning",
    hazard_kind="soft_ground",
    actions_taken=["backed off"],
)


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


@pytest.mark.parametrize(
    ("note", "category", "severity", "hazard"),
    [
        (DEMO_NOTE, "ground", Severity.warning, "soft_ground"),
        ("Hydraulic hose is leaking on the boom.", "equipment", Severity.warning, None),
        ("Diesel spill near the fuel bay.", "environment", Severity.warning, "spill"),
        ("A truck nearly backed into me at the pit.", "near_miss", Severity.warning, None),
        ("Spotter twisted his ankle on the ramp.", "injury", Severity.critical, None),
        ("Finished early, all good.", "other", Severity.info, None),
    ],
)
def test_fallback_report_keywords(note, category, severity, hazard):
    report = fallback_report(note)
    assert (report.category, report.severity, report.hazard_kind) == (category, severity, hazard)


def test_fallback_report_summary_and_actions():
    report = fallback_report(DEMO_NOTE)
    assert report.summary.startswith("Ground is soft at the edge of the haul ramp")
    assert report.actions_taken == ["I backed off and stopped work there"]


def test_llm_report_is_used(fake_llm):
    fake_llm.on(IncidentReport, LLM_REPORT)
    report, source = write_report(DEMO_NOTE)
    assert (report, source) == (LLM_REPORT, "llm")
    assert fake_llm.calls[0]["system"] == SYSTEM_PROMPT
    assert fake_llm.calls[0]["user"] == DEMO_NOTE


def test_injury_always_critical_even_if_llm_says_otherwise(fake_llm):
    fake_llm.on(IncidentReport, LLM_REPORT.model_copy(update={"category": "injury"}))
    report, _ = write_report("The spotter got hurt when the bank slipped.")
    assert report.severity == Severity.critical


def test_falls_back_without_llm():
    report, source = write_report(DEMO_NOTE)
    assert source == "fallback" and report.category == "ground"


def test_scribe_node_transcribes_audio_when_needed(fake_llm):
    fake_llm.transcripts.append("Oil on the ground by the dump.")
    state = scribe_node({"event": {"kind": "voice_note", "audio": b"\x00\x01"}})
    assert state["transcript"] == "Oil on the ground by the dump."
    assert state["incident"].category == "environment"
    with pytest.raises(ValueError):
        scribe_node({"event": {"kind": "voice_note"}})


def test_scribe_routes_through_graph():
    state = run_event(
        build_graph(scribe=scribe_node), None, {"kind": "voice_note", "transcript": DEMO_NOTE}
    )
    assert state["incident"].hazard_kind == "soft_ground"


def test_runtime_logs_the_scripted_note_at_its_minute(demo, predictor, db_session):
    runtime = ShiftRuntime(db_session, demo, predictor.predict(demo_context(demo)))
    by_minute = defaultdict(list)
    for f in demo_frames(demo):
        by_minute[f.minute].append(f)
    logged = [
        (minute, msg.incident)
        for minute in sorted(by_minute)
        for msg in runtime.process_minute(minute, by_minute[minute])
        if isinstance(msg, WsIncidentLogged)
    ]
    assert len(logged) == 1
    minute, incident = logged[0]
    assert minute == incident.minute == DEMO_SCRIPT["incident_minute"]
    assert (incident.lat, incident.lon) == (demo["incident"]["lat"], demo["incident"]["lon"])
    stored = db_session.scalars(select(Incident)).one()
    assert stored.report["hazard_kind"] == "soft_ground"


@pytest.fixture
def client(demo, predictor):
    app = create_app(make_engine("sqlite://"))
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_predictor] = lambda: predictor
    app.dependency_overrides[get_demo_timeline] = lambda: predictor.predict(demo_context(demo))
    with TestClient(app) as c:
        yield c


def test_transcribe_endpoint(client, fake_llm):
    fake_llm.transcripts.append("  soft ground at the ramp  ")
    response = client.post("/transcribe", files={"audio": ("note.webm", b"abc", "audio/webm")})
    assert response.json() == {"transcript": "soft ground at the ramp"}
    assert (
        client.post("/transcribe", files={"audio": ("n.webm", b"", "audio/webm")}).status_code
        == 400
    )
    # no transcript queued -> the fake raises LLMError -> 502
    assert (
        client.post("/transcribe", files={"audio": ("n.webm", b"x", "audio/webm")}).status_code
        == 502
    )


def test_create_incident_endpoint(client, demo):
    body = {"shift_id": 1, "minute": 10, "transcript": DEMO_NOTE, "lat": 1.0, "lon": 2.0}
    assert client.post("/incidents", json=body).status_code == 404  # no shift yet
    db = make_session_factory(client.app.state.engine)()
    seed_demo_shift(db, demo, None)
    db.close()
    response = client.post("/incidents", json=body)
    assert response.status_code == 201
    assert response.json()["report"]["category"] == "ground"


def test_voice_note_over_websocket(client):
    with client.websocket_connect("/ws/telemetry?speed=5") as ws:
        ws.receive_text()  # started
        ws.send_json({"action": "voice_note", "transcript": "Hydraulic hose leaking."})
        while True:
            msg = parse_ws_message(ws.receive_text())
            if isinstance(msg, WsIncidentLogged):
                break
        ws.send_json({"action": "stop"})
    assert msg.incident.report.category == "equipment"
