"""Live shift runtime: feeds replay minutes through the agent graph, stores what the agents
produce, and returns the WebSocket messages to broadcast."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.state import AlertDraft, GraphState, ShiftSession
from app.db import Alert, Incident, Machine, Operator, Shift, ShiftTask
from app.graph import default_graph, run_event
from app.replay import demo_context
from app.schemas import (
    AlertOut,
    IncidentOut,
    ShadowTimeline,
    TelemetryFrame,
    WsAlert,
    WsFatigue,
    WsIncidentLogged,
    WsReplan,
    WsShadowDelta,
    WsTelemetry,
)


def seed_demo_shift(db: Session, demo: dict[str, Any], timeline: ShadowTimeline | None) -> Shift:
    """Create the demo operator, machines, and a fresh demo shift (replacing any earlier run)."""
    op = demo["operator"]
    if db.get(Operator, op["id"]) is None:
        db.add(Operator(id=op["id"], name=op["name"], experience_years=op["experience_years"]))
    for m in demo["machines"]:
        if db.get(Machine, m["id"]) is None:
            db.add(Machine(id=m["id"], name=m["name"], model=m["model"], kind=m["kind"]))
    spec = demo["shift"]
    existing = db.get(Shift, spec["id"])
    if existing is not None:
        db.delete(existing)
    db.flush()

    shadow = {t.seq: t for t in timeline.tasks} if timeline else {}
    shift = Shift(
        id=spec["id"],
        operator_id=spec["operator_id"],
        machine_id=spec["machine_id"],
        started_at=datetime.fromisoformat(spec["started_at"]),
        status="live",
        weather=spec["weather"],
        site_conditions=spec["site_conditions"],
        tasks=[
            ShiftTask(
                seq=t["seq"],
                task_type=t["task_type"],
                description=t["description"],
                p10_min=shadow[t["seq"]].duration_min.p10 if shadow else None,
                p50_min=shadow[t["seq"]].duration_min.p50 if shadow else None,
                p90_min=shadow[t["seq"]].duration_min.p90 if shadow else None,
                risk_score=shadow[t["seq"]].risk_score if shadow else None,
            )
            for t in demo["tasks"]
        ],
    )
    db.add(shift)
    db.commit()
    return shift


class ShiftRuntime:
    def __init__(
        self,
        db: Session,
        demo: dict[str, Any],
        timeline: ShadowTimeline | None,
        graph: Any | None = None,
    ) -> None:
        self.db = db
        self.graph = graph or default_graph()
        shift = seed_demo_shift(db, demo, timeline)
        self.session = ShiftSession(
            shift_id=shift.id,
            machine_id=shift.machine_id,
            context=demo_context(demo),
            timeline=timeline,
        )
        # the demo operator's scripted voice note, spoken at its scripted minute
        incident = demo.get("incident")
        self.scripted_notes = {incident["minute"]: incident} if incident else {}

    def _store_alert(self, draft: AlertDraft) -> AlertOut:
        row = Alert(
            shift_id=self.session.shift_id,
            minute=draft.minute,
            kind=draft.kind.value,
            severity=draft.severity.value,
            message=draft.message,
        )
        self.db.add(row)
        self.db.commit()
        return AlertOut.model_validate(row)

    def _outputs(self, minute: int, state: GraphState) -> list[BaseModel]:
        messages: list[BaseModel] = []
        if state.get("delta_min") is not None:
            messages.append(WsShadowDelta(minute=minute, delta_min=state["delta_min"]))
        if state.get("fatigue") is not None:
            reading = state["fatigue"]
            messages.append(WsFatigue(minute=minute, score=reading.score, factors=reading.factors))
        messages.extend(WsAlert(alert=self._store_alert(a)) for a in state.get("alerts", []))
        if state.get("replan") is not None:
            messages.append(WsReplan(minute=minute, replan=state["replan"]))
        return messages

    def process_minute(self, minute: int, frames: list[TelemetryFrame]) -> list[BaseModel]:
        """Run one replay minute; returns telemetry plus everything the agents produced."""
        self.session.minute = minute
        for frame in frames:
            self.session.latest[frame.machine_id] = frame
        state = run_event(
            self.graph, self.session, {"kind": "telemetry", "minute": minute, "frames": frames}
        )
        messages = [WsTelemetry(frame=f) for f in frames] + self._outputs(minute, state)
        note = self.scripted_notes.get(minute)
        if note is not None:
            messages += self.voice_note(minute, transcript=note["transcript"])
        return messages

    def voice_note(
        self,
        minute: int,
        transcript: str | None = None,
        audio: bytes | None = None,
        lat: float | None = None,
        lon: float | None = None,
    ) -> list[BaseModel]:
        """Run a voice note through the Scribe and store the incident at the machine's spot."""
        me = self.session.me
        state = run_event(
            self.graph,
            self.session,
            {"kind": "voice_note", "minute": minute, "transcript": transcript, "audio": audio},
        )
        row = Incident(
            shift_id=self.session.shift_id,
            minute=minute,
            transcript=state["transcript"],
            report=state["incident"].model_dump(mode="json"),
            lat=lat if lat is not None else (me.lat if me else None),
            lon=lon if lon is not None else (me.lon if me else None),
        )
        self.db.add(row)
        self.db.commit()
        return [WsIncidentLogged(incident=IncidentOut.model_validate(row))]
