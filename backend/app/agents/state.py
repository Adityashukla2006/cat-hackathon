"""Shared runtime state for one live shift, passed through the agent graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from app.schemas import (
    AlertKind,
    Briefing,
    IncidentReport,
    Replan,
    Severity,
    ShadowTimeline,
    ShiftContext,
    TelemetryFrame,
)


@dataclass(frozen=True)
class AlertDraft:
    """An alert an agent wants raised. The runtime persists and broadcasts it."""

    minute: int
    kind: AlertKind
    severity: Severity
    message: str


@dataclass
class ShiftSession:
    """Everything the agents remember about the shift between events."""

    shift_id: int
    machine_id: int
    context: ShiftContext
    timeline: ShadowTimeline | None = None
    task_order: list[int] = field(default_factory=list)
    latest: dict[int, TelemetryFrame] = field(default_factory=dict)
    minute: int = 0
    memory: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_order:
            self.task_order = [t.seq for t in sorted(self.context.tasks, key=lambda t: t.seq)]

    @property
    def me(self) -> TelemetryFrame | None:
        """Latest frame from the operator's own machine."""
        return self.latest.get(self.machine_id)


class ShiftEvent(TypedDict, total=False):
    kind: Literal["plan", "telemetry", "voice_note"]
    minute: int
    frames: list[TelemetryFrame]
    transcript: str | None
    audio: bytes | None
    lat: float | None
    lon: float | None


class GraphState(TypedDict, total=False):
    session: ShiftSession
    event: ShiftEvent
    alerts: list[AlertDraft]
    needs_replan: bool
    replan_reason: str | None
    replan: Replan | None
    briefing: Briefing | None
    incident: IncidentReport | None
