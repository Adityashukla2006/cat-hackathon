from collections import defaultdict

import pytest
from sqlalchemy import select

from app.agents.sentinel import (
    BEHIND_MIN,
    FUEL_WINDOW_MIN,
    IDLE_STREAK_MIN,
    REPLAN_COOLDOWN_MIN,
    SentinelState,
    check_behind,
    check_fuel,
    check_idle,
    check_seatbelt,
    sentinel_node,
)
from app.agents.state import ShiftSession
from app.db import Alert, Shift
from app.graph import build_graph, run_event
from app.replay import demo_context, demo_frames
from app.runtime import ShiftRuntime, seed_demo_shift
from app.schemas import (
    AlertKind,
    QuantileRange,
    Severity,
    ShadowTask,
    TelemetryFrame,
    WsAlert,
    WsShadowDelta,
    WsTelemetry,
)
from data.generate import DEMO_SCRIPT, generate


def _frame(**overrides) -> TelemetryFrame:
    data = dict(
        shift_id=1,
        machine_id=1,
        minute=0,
        lat=0.0,
        lon=0.0,
        engine_on=True,
        seatbelt=True,
        idle=False,
        fuel_rate_lph=20.0,
        speed_kph=2.0,
        load_pct=60.0,
        task_seq=1,
    )
    data.update(overrides)
    return TelemetryFrame(**data)


TASK = ShadowTask(
    seq=1,
    task_type="dig",
    description="Dig",
    duration_min=QuantileRange(p10=40, p50=50, p90=60),
    start_min=0,
    expected_idle_min=4,
    expected_fuel_l=16.5,  # 16.5 L over 46 working minutes, about 21.5 L/h
)


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


def test_seatbelt_alerts_once_per_episode():
    st = SentinelState()
    first = check_seatbelt(st, _frame(seatbelt=False, minute=2))
    assert first.kind == AlertKind.seatbelt and first.severity == Severity.critical
    assert check_seatbelt(st, _frame(seatbelt=False, minute=3)) is None
    assert check_seatbelt(st, _frame(seatbelt=True, minute=4)) is None
    assert check_seatbelt(st, _frame(seatbelt=False, minute=5)) is not None


def test_seatbelt_ignored_with_engine_off():
    assert check_seatbelt(SentinelState(), _frame(engine_on=False, seatbelt=False)) is None


def test_idle_streak_triggers_once_per_task():
    st = SentinelState()
    results = [check_idle(st, _frame(minute=m, idle=True), TASK) for m in range(IDLE_STREAK_MIN)]
    assert results[:-1] == [None] * (IDLE_STREAK_MIN - 1)
    assert results[-1].kind == AlertKind.idle_deviation
    assert f"{IDLE_STREAK_MIN} min straight" in results[-1].message
    assert check_idle(st, _frame(minute=20, idle=True), TASK) is None


def test_scattered_idle_beyond_expectation_triggers():
    st = SentinelState()
    alert = None
    for m in range(60):
        alert = check_idle(st, _frame(minute=m, idle=m % 3 == 0), TASK) or alert
    assert alert is not None and "shadow expected 4" in alert.message


def test_prestart_warmup_idle_is_ignored():
    st = SentinelState()
    for m in range(20):
        assert check_idle(st, _frame(minute=m, idle=True, task_seq=None), None) is None


def test_behind_alert_has_hysteresis():
    st = SentinelState()
    assert check_behind(st, 1, -BEHIND_MIN + 1) is None
    assert check_behind(st, 2, -BEHIND_MIN).kind == AlertKind.cycle_deviation
    assert check_behind(st, 3, -BEHIND_MIN - 5) is None
    assert check_behind(st, 4, -BEHIND_MIN / 2 + 1) is None  # recovered, re-arms
    assert check_behind(st, 5, -BEHIND_MIN - 1) is not None
    assert check_behind(st, 6, None) is None


def test_fuel_alert_needs_a_full_window_above_ratio():
    st = SentinelState()
    for m in range(FUEL_WINDOW_MIN):
        assert check_fuel(st, _frame(minute=m, fuel_rate_lph=22.0), TASK) is None
    st = SentinelState()
    results = [
        check_fuel(st, _frame(minute=m, fuel_rate_lph=35.0), TASK) for m in range(FUEL_WINDOW_MIN)
    ]
    assert results[-1].kind == AlertKind.fuel_deviation
    assert check_fuel(st, _frame(minute=99, fuel_rate_lph=35.0), TASK) is None


def _session(demo, predictor) -> ShiftSession:
    ctx = demo_context(demo)
    return ShiftSession(shift_id=1, machine_id=1, context=ctx, timeline=predictor.predict(ctx))


def test_node_requests_replan_with_cooldown(demo, predictor):
    session = _session(demo, predictor)
    graph = build_graph(sentinel=sentinel_node)
    replans = []
    for minute in range(7, 7 + REPLAN_COOLDOWN_MIN + 40):
        session.latest[1] = _frame(minute=minute, idle=True)
        if minute == 30:
            session.latest[1] = _frame(minute=minute, idle=True, task_seq=2)
        state = run_event(graph, session, {"kind": "telemetry", "minute": minute})
        if state["needs_replan"]:
            replans.append((minute, state["replan_reason"]))
    # task 1 idle streak at minute 16, task 2 alert is inside the cooldown, no second replan
    assert [m for m, _ in replans] == [16]
    assert "idle" in replans[0][1].lower()


def test_node_skips_when_machine_has_no_frame_this_minute(demo, predictor):
    session = _session(demo, predictor)
    session.latest[1] = _frame(minute=3)
    state = sentinel_node({"session": session, "event": {"kind": "telemetry", "minute": 4}})
    assert state == {"alerts": [], "needs_replan": False}


def test_runtime_replays_demo_with_scripted_alerts(demo, predictor, db_session):
    timeline = predictor.predict(demo_context(demo))
    runtime = ShiftRuntime(db_session, demo, timeline)
    by_minute = defaultdict(list)
    for frame in demo_frames(demo):
        by_minute[frame.minute].append(frame)

    alerts, deltas, telemetry = [], 0, 0
    for minute in sorted(by_minute):
        for msg in runtime.process_minute(minute, by_minute[minute]):
            if isinstance(msg, WsAlert):
                alerts.append(msg.alert)
            deltas += isinstance(msg, WsShadowDelta)
            telemetry += isinstance(msg, WsTelemetry)

    assert telemetry == 960 and deltas > 400
    kinds = {a.kind: a.minute for a in alerts}
    belt_lo, belt_hi = DEMO_SCRIPT["seatbelt_unbuckled"]
    idle_lo, idle_hi = DEMO_SCRIPT["idle_window"]
    assert belt_lo <= kinds[AlertKind.seatbelt] <= belt_hi
    assert idle_lo <= kinds[AlertKind.idle_deviation] <= idle_hi
    stored = db_session.scalars(select(Alert).order_by(Alert.minute)).all()
    assert [a.id for a in alerts] == [a.id for a in stored]


def test_seed_demo_shift_replaces_previous_run(demo, predictor, db_session):
    timeline = predictor.predict(demo_context(demo))
    shift = seed_demo_shift(db_session, demo, timeline)
    db_session.add(
        Alert(shift_id=shift.id, minute=1, kind="seatbelt", severity="critical", message="x")
    )
    db_session.commit()
    shift = seed_demo_shift(db_session, demo, timeline)
    assert db_session.scalars(select(Alert)).all() == []
    assert db_session.get(Shift, shift.id).tasks[0].p50_min == timeline.tasks[0].duration_min.p50
