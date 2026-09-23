from collections import defaultdict

import pytest

from app.agents.dispatcher import (
    SYSTEM_PROMPT,
    DispatchNote,
    dispatcher_node,
    plan_order,
    template_explanation,
)
from app.agents.sentinel import get_state
from app.agents.state import ShiftSession
from app.replay import demo_context, demo_frames
from app.runtime import ShiftRuntime
from app.schemas import TelemetryFrame, WsReplan
from app.shadow.predictor import reorder_timeline
from data.generate import DEMO_EXECUTION_ORDER, DEMO_SCRIPT, generate


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


@pytest.fixture
def session(demo, predictor) -> ShiftSession:
    ctx = demo_context(demo)
    return ShiftSession(shift_id=1, machine_id=1, context=ctx, timeline=predictor.predict(ctx))


def _on_task(session: ShiftSession, seq: int) -> None:
    session.latest[1] = TelemetryFrame(
        shift_id=1,
        machine_id=1,
        minute=100,
        lat=0,
        lon=0,
        engine_on=True,
        seatbelt=True,
        idle=True,
        fuel_rate_lph=4,
        speed_kph=0,
        load_pct=0,
        task_seq=seq,
    )


def test_reorder_timeline_recomputes_start_times(session):
    reordered = reorder_timeline(session.timeline, [2, 1, 3, 4, 5, 6])
    by_seq = {t.seq: t for t in session.timeline.tasks}
    assert [t.seq for t in reordered.tasks] == [2, 1, 3, 4, 5, 6]
    assert reordered.tasks[0].start_min == 0
    assert reordered.tasks[1].start_min == pytest.approx(by_seq[2].duration_min.p50, abs=0.01)
    assert reordered.total_min == session.timeline.total_min
    with pytest.raises(ValueError):
        reorder_timeline(session.timeline, [1, 2])


def test_plan_keeps_done_and_active_tasks_and_sorts_rest_by_risk(session):
    _on_task(session, 3)
    plan = plan_order(session)
    assert plan.done_or_active == [1, 2, 3]
    assert plan.new_order == DEMO_EXECUTION_ORDER
    risks = [plan.risk[s] for s in plan.new_remaining]
    assert risks == sorted(risks, reverse=True)


def test_hazard_zone_tasks_are_deferred(session):
    session.memory["hazard_zones"] = ["stockpile"]
    _on_task(session, 3)
    plan = plan_order(session)
    assert plan.deferred == [6]
    assert plan.new_remaining[-1] == 6
    assert "hazard-zone work last" in template_explanation(plan, None)


def test_node_applies_replan_and_uses_llm_explanation(session, fake_llm):
    fake_llm.on(DispatchNote, DispatchNote(explanation="Stockpile first while you're fresh."))
    _on_task(session, 3)
    tracker = get_state(session).tracker
    state = dispatcher_node({"session": session, "replan_reason": "Idle 10 min straight"})
    replan = state["replan"]
    assert replan.new_order == DEMO_EXECUTION_ORDER
    assert replan.explanation == "Stockpile first while you're fresh."
    assert session.task_order == DEMO_EXECUTION_ORDER
    assert [t.seq for t in session.timeline.tasks] == DEMO_EXECUTION_ORDER
    assert tracker.timeline is session.timeline
    assert fake_llm.calls[0]["system"] == SYSTEM_PROMPT
    assert "Idle 10 min straight" in fake_llm.calls[0]["user"]


def test_node_falls_back_to_template_when_llm_fails(session, fake_llm):
    _on_task(session, 3)
    replan = dispatcher_node({"session": session})["replan"]
    assert replan.explanation.startswith("Next up: build stockpile")


def test_node_skips_replan_when_order_already_fits(session, fake_llm):
    _on_task(session, 3)
    dispatcher_node({"session": session})
    calls = len(fake_llm.calls)
    assert dispatcher_node({"session": session}) == {"replan": None}
    assert len(fake_llm.calls) == calls


def test_demo_replan_fires_after_the_idle_deviation(demo, predictor, db_session, fake_llm):
    runtime = ShiftRuntime(db_session, demo, predictor.predict(demo_context(demo)))
    by_minute = defaultdict(list)
    for f in demo_frames(demo):
        by_minute[f.minute].append(f)
    replans = [
        msg
        for minute in sorted(by_minute)
        for msg in runtime.process_minute(minute, by_minute[minute])
        if isinstance(msg, WsReplan)
    ]
    assert len(replans) == 1
    idle_lo, idle_hi = DEMO_SCRIPT["idle_window"]
    assert idle_lo <= replans[0].minute <= idle_hi
    assert replans[0].replan.new_order == DEMO_EXECUTION_ORDER
