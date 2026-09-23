"""Fatigue score: deterministic 0-1 estimate from time on shift and the operator's own
performance drift. Safety-critical, so no LLM involvement.

  hours      time since shift start, saturating at 10 h
  no_break   time since the last break (engine off for BREAK_MIN+ minutes), saturating at 4 h
  slowdown   load in the current task vs the start of the same task (task types differ in load,
             so comparing across tasks would mistake a lighter task for fatigue)
  idling     share of short pauses (micro-pauses) above the early-shift baseline; long waits are
             an idle deviation, not fatigue, so they are left out
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.schemas import TelemetryFrame

WEIGHTS = {"hours": 0.35, "no_break": 0.2, "slowdown": 0.3, "idling": 0.15}
FULL_HOURS = 10.0
FULL_NO_BREAK_MIN = 240.0
FULL_SLOWDOWN = 0.25  # a 25% drop in load counts fully
FULL_EXTRA_PAUSES = 0.15
BREAK_MIN = 10
MICRO_PAUSE_MAX = 3
BASELINE_MIN = 90
RECENT_MIN = 30
TASK_BASELINE_MIN = 10
TASK_RECENT_MIN = 20
ALERT_AT = 0.6
REARM_BELOW = 0.45


class FatigueReading(BaseModel):
    minute: int
    score: float
    factors: dict[str, float]

    def top_reasons(self) -> list[str]:
        labels = {
            "hours": "long time on shift",
            "no_break": "no break yet",
            "slowdown": "cycles slowing down",
            "idling": "more pauses than usual",
        }
        # what the operator is doing differently says more than the clock, so it goes first
        behaviour = [k for k in ("slowdown", "idling") if self.factors.get(k, 0) >= 0.05]
        clock = sorted(("hours", "no_break"), key=lambda k: -self.factors.get(k, 0))
        return [labels[k] for k in behaviour + clock if self.factors.get(k, 0) >= 0.05][:2]


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values)


@dataclass
class FatigueTracker:
    engine_off_streak: int = 0
    idle_streak: int = 0
    last_break_minute: int = 0
    baseline_pauses: list[bool] = field(default_factory=list)
    recent_pauses: deque[bool] = field(default_factory=lambda: deque(maxlen=RECENT_MIN))
    task_seq: int | None = None
    task_baseline: list[float] = field(default_factory=list)
    task_recent: deque[float] = field(default_factory=lambda: deque(maxlen=TASK_RECENT_MIN))
    alerted: bool = False

    def update(self, frame: TelemetryFrame) -> FatigueReading:
        self._track_breaks(frame)
        if frame.engine_on and frame.task_seq is not None:
            self._track_pauses(frame)
            self._track_task_load(frame)

        factors = {
            "hours": min(frame.minute / 60.0 / FULL_HOURS, 1.0),
            "no_break": min((frame.minute - self.last_break_minute) / FULL_NO_BREAK_MIN, 1.0),
            "slowdown": self._slowdown(),
            "idling": self._extra_pauses(),
        }
        weighted = {k: round(WEIGHTS[k] * v, 3) for k, v in factors.items()}
        return FatigueReading(
            minute=frame.minute, score=round(min(sum(weighted.values()), 1.0), 3), factors=weighted
        )

    def _track_breaks(self, frame: TelemetryFrame) -> None:
        self.engine_off_streak = 0 if frame.engine_on else self.engine_off_streak + 1
        if self.engine_off_streak >= BREAK_MIN:
            self.last_break_minute = frame.minute

    def _track_pauses(self, frame: TelemetryFrame) -> None:
        self.idle_streak = self.idle_streak + 1 if frame.idle else 0
        if self.idle_streak > MICRO_PAUSE_MAX:
            return  # a long wait, not a fatigue pause
        target = (
            self.baseline_pauses if len(self.baseline_pauses) < BASELINE_MIN else self.recent_pauses
        )
        target.append(frame.idle)

    def _track_task_load(self, frame: TelemetryFrame) -> None:
        if frame.task_seq != self.task_seq:
            self.task_seq = frame.task_seq
            self.task_baseline.clear()
            self.task_recent.clear()
        if frame.idle:
            return
        if len(self.task_baseline) < TASK_BASELINE_MIN:
            self.task_baseline.append(frame.load_pct)
        else:
            self.task_recent.append(frame.load_pct)

    def _slowdown(self) -> float:
        if len(self.task_recent) < TASK_RECENT_MIN:
            return 0.0
        base = _mean(self.task_baseline)
        drop = (base - _mean(self.task_recent)) / base if base else 0.0
        return min(max(drop, 0.0) / FULL_SLOWDOWN, 1.0)

    def _extra_pauses(self) -> float:
        if len(self.recent_pauses) < RECENT_MIN:
            return 0.0
        extra = _mean(self.recent_pauses) - _mean(self.baseline_pauses)
        return min(max(extra, 0.0) / FULL_EXTRA_PAUSES, 1.0)

    def should_alert(self, reading: FatigueReading) -> bool:
        """True once each time the score climbs past ALERT_AT (re-arms below REARM_BELOW)."""
        if reading.score < REARM_BELOW:
            self.alerted = False
        if reading.score >= ALERT_AT and not self.alerted:
            self.alerted = True
            return True
        return False
