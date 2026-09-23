import pytest

from app.agents.fatigue import (
    ALERT_AT,
    BASELINE_MIN,
    BREAK_MIN,
    RECENT_MIN,
    TASK_BASELINE_MIN,
    TASK_RECENT_MIN,
    WEIGHTS,
    FatigueReading,
    FatigueTracker,
)
from app.schemas import TelemetryFrame


def _frame(minute: int, **overrides) -> TelemetryFrame:
    data = dict(
        shift_id=1,
        machine_id=1,
        minute=minute,
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


def test_fresh_operator_scores_near_zero():
    reading = FatigueTracker().update(_frame(0))
    assert reading.score == 0.0


def test_time_on_shift_and_no_break_raise_score():
    tracker = FatigueTracker()
    for m in range(300):
        reading = tracker.update(_frame(m))
    assert reading.factors["hours"] == pytest.approx(WEIGHTS["hours"] * 299 / 600, abs=0.001)
    assert reading.factors["no_break"] == WEIGHTS["no_break"]
    assert reading.factors["slowdown"] == 0 and reading.factors["idling"] == 0


def test_a_break_resets_the_no_break_factor():
    tracker = FatigueTracker()
    for m in range(200):
        tracker.update(_frame(m))
    for m in range(200, 200 + BREAK_MIN):
        tracker.update(_frame(m, engine_on=False, task_seq=None))
    reading = tracker.update(_frame(200 + BREAK_MIN))
    assert reading.factors["no_break"] == pytest.approx(0.0, abs=0.001)


def test_load_drop_within_a_task_counts_as_slowdown():
    tracker = FatigueTracker()
    minute = 0
    for _ in range(TASK_BASELINE_MIN):
        tracker.update(_frame(minute, load_pct=80.0))
        minute += 1
    for _ in range(TASK_RECENT_MIN):
        reading = tracker.update(_frame(minute, load_pct=60.0))  # 25% drop
        minute += 1
    assert reading.factors["slowdown"] == pytest.approx(WEIGHTS["slowdown"])


def test_switching_to_a_lighter_task_is_not_slowdown():
    tracker = FatigueTracker()
    for m in range(40):
        tracker.update(_frame(m, load_pct=80.0, task_seq=1))
    for m in range(40, 80):
        reading = tracker.update(_frame(m, load_pct=45.0, task_seq=2))
    assert reading.factors["slowdown"] == 0.0


def test_frequent_short_pauses_count_but_one_long_wait_does_not():
    short = FatigueTracker()
    for m in range(BASELINE_MIN):
        short.update(_frame(m))
    for m in range(BASELINE_MIN, BASELINE_MIN + RECENT_MIN):
        reading = short.update(_frame(m, idle=m % 4 == 0))  # 25% short pauses
    assert reading.factors["idling"] == pytest.approx(WEIGHTS["idling"])

    long_wait = FatigueTracker()
    for m in range(BASELINE_MIN):
        long_wait.update(_frame(m))
    for m in range(BASELINE_MIN, BASELINE_MIN + 25):
        long_wait.update(_frame(m, idle=True))
    for m in range(BASELINE_MIN + 25, BASELINE_MIN + 60):
        reading = long_wait.update(_frame(m))
    assert reading.factors["idling"] <= 0.02


def test_alert_fires_once_and_rearms():
    tracker = FatigueTracker()
    high = FatigueReading(minute=1, score=ALERT_AT + 0.1, factors={})
    assert tracker.should_alert(high) is True
    assert tracker.should_alert(high) is False
    tracker.should_alert(FatigueReading(minute=2, score=0.1, factors={}))
    assert tracker.should_alert(high) is True


def test_reasons_put_behaviour_before_the_clock():
    reading = FatigueReading(
        minute=1, score=0.8, factors={"hours": 0.25, "no_break": 0.2, "slowdown": 0.1, "idling": 0}
    )
    assert reading.top_reasons() == ["cycles slowing down", "long time on shift"]


def test_demo_fatigue_alert_only_in_the_scripted_window(predictor):
    from collections import defaultdict

    from app.agents.sentinel import SentinelState, check_fatigue
    from app.replay import demo_frames
    from data.generate import DEMO_SCRIPT, generate

    demo = generate(seed=42, n_shifts=2)["demo"]
    st = SentinelState()
    alerts = []
    by_minute = defaultdict(list)
    for f in demo_frames(demo):
        by_minute[f.minute].append(f)
    for minute in sorted(by_minute):
        me = next(f for f in by_minute[minute] if f.machine_id == 1)
        alert = check_fatigue(st, st.fatigue.update(me))
        if alert:
            alerts.append(alert)
    assert len(alerts) == 1
    assert alerts[0].minute >= DEMO_SCRIPT["fatigue_from_minute"]
    assert "cycles slowing down" in alerts[0].message
