"""Follows one machine's live telemetry against its shadow timeline."""

from __future__ import annotations

from app.schemas import ShadowTimeline, TelemetryFrame
from app.shadow.predictor import schedule_delta


class ShadowTracker:
    def __init__(self, timeline: ShadowTimeline, machine_id: int) -> None:
        self.timeline = timeline
        self.machine_id = machine_id
        self.task_seq: int | None = None
        self.task_started_min: int | None = None

    def update(self, frame: TelemetryFrame) -> float | None:
        """Return minutes ahead (+) / behind (-) the shadow, or None if not applicable."""
        if frame.machine_id != self.machine_id or frame.task_seq is None:
            return None
        if frame.task_seq != self.task_seq:
            self.task_seq = frame.task_seq
            self.task_started_min = frame.minute
        return schedule_delta(self.timeline, frame.minute, self.task_seq, self.task_started_min)
