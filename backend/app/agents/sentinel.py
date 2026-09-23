"""Sentinel: deterministic safety rules and deviation checks. No LLM calls, ever.

Rules run on every telemetry minute for the operator's own machine:
  seatbelt        engine on with the seatbelt unbuckled
  idle_deviation  a long idle streak, or idle in a task well beyond the shadow's expectation
  cycle_deviation falling well behind the shadow timeline
  fuel_deviation  burning well above the shadow's expected fuel rate
  fatigue         the fatigue score (app/agents/fatigue.py) climbs past its alert level
  hazard          any machine approaching an active site-memory hazard pin (geofence)
Deviations that change the plan ask the Dispatcher for a replan, with a cooldown.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.agents.fatigue import FatigueReading, FatigueTracker
from app.agents.state import AlertDraft, GraphState, ShiftSession
from app.schemas import AlertKind, Severity, ShadowTask, TelemetryFrame, WsHazardWarning
from app.shadow.tracker import ShadowTracker
from app.site_memory import ProximityWatch

IDLE_STREAK_MIN = 10
IDLE_EXCESS_MIN = 10.0
BEHIND_MIN = 15.0
REPLAN_COOLDOWN_MIN = 45
FUEL_WINDOW_MIN = 15
FUEL_RATIO = 1.35


@dataclass
class SentinelState:
    tracker: ShadowTracker | None = None
    seatbelt_alerted: bool = False
    idle_streak: int = 0
    idle_by_task: dict[int, int] = field(default_factory=dict)
    idle_alerted_tasks: set[int] = field(default_factory=set)
    behind_alerted: bool = False
    fuel_window: deque[float] = field(default_factory=lambda: deque(maxlen=FUEL_WINDOW_MIN))
    fuel_alerted_tasks: set[int] = field(default_factory=set)
    last_replan_minute: int | None = None
    fatigue: FatigueTracker = field(default_factory=FatigueTracker)
    proximity: ProximityWatch = field(default_factory=ProximityWatch)


def get_state(session: ShiftSession) -> SentinelState:
    state = session.memory.get("sentinel")
    if state is None:
        tracker = ShadowTracker(session.timeline, session.machine_id) if session.timeline else None
        state = session.memory["sentinel"] = SentinelState(tracker=tracker)
    return state


def check_seatbelt(st: SentinelState, frame: TelemetryFrame) -> AlertDraft | None:
    if not frame.engine_on or frame.seatbelt:
        st.seatbelt_alerted = False
        return None
    if st.seatbelt_alerted:
        return None
    st.seatbelt_alerted = True
    return AlertDraft(
        frame.minute,
        AlertKind.seatbelt,
        Severity.critical,
        "Seatbelt unbuckled with the engine on. Lower the bucket and buckle up.",
    )


def check_idle(
    st: SentinelState, frame: TelemetryFrame, task: ShadowTask | None
) -> AlertDraft | None:
    working_idle = frame.idle and frame.engine_on
    st.idle_streak = st.idle_streak + 1 if working_idle else 0
    if task is None or frame.task_seq is None:
        return None
    if working_idle:
        st.idle_by_task[task.seq] = st.idle_by_task.get(task.seq, 0) + 1
    idle_in_task = st.idle_by_task.get(task.seq, 0)
    too_long = st.idle_streak >= IDLE_STREAK_MIN
    too_much = idle_in_task > task.expected_idle_min + IDLE_EXCESS_MIN
    if task.seq in st.idle_alerted_tasks or not (too_long or too_much):
        return None
    st.idle_alerted_tasks.add(task.seq)
    if too_long:
        what = f"Idle {st.idle_streak} min straight on task {task.seq}."
    else:
        what = (
            f"Idle {idle_in_task} min on task {task.seq}, "
            f"shadow expected {task.expected_idle_min:.0f}."
        )
    return AlertDraft(
        frame.minute,
        AlertKind.idle_deviation,
        Severity.warning,
        f"{what} If you're waiting on something, tell dispatch.",
    )


def check_behind(st: SentinelState, minute: int, delta: float | None) -> AlertDraft | None:
    if delta is None:
        return None
    if delta > -BEHIND_MIN / 2:
        st.behind_alerted = False
        return None
    if delta > -BEHIND_MIN or st.behind_alerted:
        return None
    st.behind_alerted = True
    return AlertDraft(
        minute,
        AlertKind.cycle_deviation,
        Severity.warning,
        f"{abs(delta):.0f} min behind the shadow plan.",
    )


def check_fuel(
    st: SentinelState, frame: TelemetryFrame, task: ShadowTask | None
) -> AlertDraft | None:
    if task is None or frame.idle or not frame.engine_on:
        return None
    st.fuel_window.append(frame.fuel_rate_lph)
    working_min = max(task.duration_min.p50 - task.expected_idle_min, 1.0)
    expected_lph = task.expected_fuel_l / working_min * 60.0
    if (
        len(st.fuel_window) < FUEL_WINDOW_MIN
        or task.seq in st.fuel_alerted_tasks
        or sum(st.fuel_window) / len(st.fuel_window) <= expected_lph * FUEL_RATIO
    ):
        return None
    st.fuel_alerted_tasks.add(task.seq)
    return AlertDraft(
        frame.minute,
        AlertKind.fuel_deviation,
        Severity.info,
        f"Fuel burn is well above the shadow's {expected_lph:.0f} L/h for this task.",
    )


def check_fatigue(st: SentinelState, reading: FatigueReading) -> AlertDraft | None:
    if not st.fatigue.should_alert(reading):
        return None
    reasons = " and ".join(reading.top_reasons()) or "time on shift"
    return AlertDraft(
        reading.minute,
        AlertKind.fatigue,
        Severity.warning,
        f"Fatigue is building ({reasons}). Park safely and take a 10-minute break.",
    )


def check_hazards(
    st: SentinelState, session: ShiftSession, frames: list[TelemetryFrame]
) -> tuple[list[AlertDraft], list[WsHazardWarning]]:
    pins = session.memory.get("pins", [])
    alerts: list[AlertDraft] = []
    warnings: list[WsHazardWarning] = []
    for frame in frames:
        for pin, dist in st.proximity.check(frame, pins):
            warnings.append(WsHazardWarning(machine_id=frame.machine_id, pin=pin, distance_m=dist))
            if frame.machine_id == session.machine_id:
                alerts.append(
                    AlertDraft(
                        frame.minute,
                        AlertKind.hazard_proximity,
                        Severity.warning,
                        f"{pin.description} Reported {dist:.0f} m away. Slow down and keep clear.",
                    )
                )
    return alerts, warnings


def _task(session: ShiftSession, seq: int | None) -> ShadowTask | None:
    if session.timeline is None or seq is None:
        return None
    return next((t for t in session.timeline.tasks if t.seq == seq), None)


def sentinel_node(state: GraphState) -> dict[str, Any]:
    session = state["session"]
    frame = session.me
    if frame is None or frame.minute != state["event"].get("minute", frame.minute):
        return {"alerts": [], "needs_replan": False}
    st = get_state(session)
    task = _task(session, frame.task_seq)
    delta = st.tracker.update(frame) if st.tracker else None
    fatigue = st.fatigue.update(frame)
    hazard_alerts, hazard_warnings = check_hazards(
        st, session, state["event"].get("frames") or [frame]
    )

    alerts = [
        a
        for a in (
            check_seatbelt(st, frame),
            check_idle(st, frame, task),
            check_behind(st, frame.minute, delta),
            check_fuel(st, frame, task),
            check_fatigue(st, fatigue),
        )
        if a is not None
    ] + hazard_alerts

    replan_kinds = {AlertKind.idle_deviation, AlertKind.cycle_deviation}
    triggers = [a for a in alerts if a.kind in replan_kinds]
    cooled = (
        st.last_replan_minute is None or frame.minute - st.last_replan_minute >= REPLAN_COOLDOWN_MIN
    )
    needs_replan = bool(triggers) and cooled
    if needs_replan:
        st.last_replan_minute = frame.minute
    return {
        "alerts": alerts,
        "delta_min": delta,
        "fatigue": fatigue,
        "hazard_warnings": hazard_warnings,
        "needs_replan": needs_replan,
        "replan_reason": triggers[0].message if needs_replan else None,
    }
