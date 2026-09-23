from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from app.agents.handover import SYSTEM_PROMPT, HandoverText, build_handover
from app.db import Shift, make_engine
from app.main import create_app
from app.replay import demo_context, demo_frames
from app.runtime import ShiftRuntime
from data.generate import DEMO_EXECUTION_ORDER, generate


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


@pytest.fixture
def finished(demo, predictor, db_session):
    runtime = ShiftRuntime(db_session, demo, predictor.predict(demo_context(demo)))
    by_minute = defaultdict(list)
    for f in demo_frames(demo):
        by_minute[f.minute].append(f)
    for minute in sorted(by_minute):
        runtime.process_minute(minute, by_minute[minute])
    return runtime


def test_runtime_tracks_task_status(finished, db_session, demo):
    tasks = {t.seq: t for t in db_session.get(Shift, 1).tasks}
    last = DEMO_EXECUTION_ORDER[-1]
    assert tasks[last].status == "active"
    for seq in DEMO_EXECUTION_ORDER[:-1]:
        planned = next(t for t in demo["tasks"] if t["seq"] == seq)
        assert tasks[seq].status == "done"
        assert tasks[seq].actual_min == planned["actual_min"]


def test_template_handover_from_the_demo(finished, db_session):
    handover = build_handover(db_session, 1, finished.session.now, finished.session)
    assert handover.source == "template"
    behind = abs(finished.session.memory["last_delta"])
    assert handover.headline == f"5 tasks done, {behind:.0f} min behind plan."
    assert handover.done[0].startswith("Dig pit face A (66 min vs ")
    assert handover.carry_over == ["Load haul trucks at the pit (in progress)"]
    assert handover.watch_outs[0].startswith("Ground is soft at the edge of the haul ramp")
    assert any("Seatbelt" in w for w in handover.watch_outs)
    assert [h.kind for h in handover.hazards] == ["soft_ground"]
    assert len(handover.open_alerts) == 4


def test_llm_handover_gets_the_facts(finished, db_session, fake_llm):
    fake_llm.on(
        HandoverText,
        HandoverText(headline="5 done.", carry_over=["Load trucks"], watch_outs=["Soft ramp edge"]),
    )
    handover = build_handover(db_session, 1, finished.session.now, finished.session)
    assert (handover.source, handover.headline) == ("llm", "5 done.")
    call = fake_llm.calls[-1]
    assert call["system"] == SYSTEM_PROMPT
    assert "Ground is soft at the edge of the haul ramp" in call["user"]
    assert f'"minutes_vs_shadow": {finished.session.memory["last_delta"]}' in call["user"]


def test_handover_without_a_live_session(finished, db_session):
    handover = build_handover(db_session, 1, finished.session.now)
    assert handover.minutes_vs_shadow is None
    assert handover.headline == "5 tasks done."


def test_unknown_shift_raises(db_session, predictor):
    with pytest.raises(LookupError):
        build_handover(db_session, 42, None)


def test_handover_endpoint_404():
    app = create_app(make_engine("sqlite://"))
    with TestClient(app) as client:
        assert client.get("/shifts/42/handover").status_code == 404
