"""Follows one machine's live telemetry against its shadow timeline."""

from __future__ import annotations

from app.schemas import ShadowTimeline, TelemetryFrame
from app.shadow.predictor import schedule_delta


class ShadowTracker:
    """Credits working minutes, plus idle only up to the shadow's expected idle for the task.

    Unplanned idle therefore shows up as falling behind the shadow.
    """

    def __init__(self, timeline: ShadowTimeline, machine_id: int) -> None:
        self.timeline = timeline
        self.machine_id = machine_id
        self._expected_idle = {t.seq: t.expected_idle_min for t in timeline.tasks}
        self.task_seq: int | None = None
        self.work_min = 0
        self.idle_min = 0

    @property
    def progress_min(self) -> float:
        allowed_idle = self._expected_idle.get(self.task_seq, 0.0)
        return self.work_min + min(self.idle_min, allowed_idle)

    def update(self, frame: TelemetryFrame) -> float | None:
        """Return minutes ahead (+) / behind (-) the shadow, or None if not applicable."""
        if frame.machine_id != self.machine_id or frame.task_seq is None:
            return None
        if frame.task_seq != self.task_seq:
            self.task_seq = frame.task_seq
            self.work_min = self.idle_min = 0
        if frame.idle:
            self.idle_min += 1
        else:
            self.work_min += 1
        return schedule_delta(self.timeline, frame.minute + 1, self.task_seq, self.progress_min)
