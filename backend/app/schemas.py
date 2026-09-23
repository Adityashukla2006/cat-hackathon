"""Pydantic API contracts shared by routes, agents, and the WebSocket stream."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class AlertKind(str, Enum):
    seatbelt = "seatbelt"
    idle_deviation = "idle_deviation"
    cycle_deviation = "cycle_deviation"
    fuel_deviation = "fuel_deviation"
    fatigue = "fatigue"
    hazard_proximity = "hazard_proximity"
    speed = "speed"


class TaskStatus(str, Enum):
    pending = "pending"
    active = "active"
    done = "done"
    skipped = "skipped"


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- health ---------------------------------------------------------------


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool


# --- shadow predictions ---------------------------------------------------


class QuantileRange(BaseModel):
    p10: float = Field(ge=0)
    p50: float = Field(ge=0)
    p90: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> QuantileRange:
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("quantiles must satisfy p10 <= p50 <= p90")
        return self


class PlannedTask(BaseModel):
    seq: int = Field(ge=1)
    task_type: Literal["dig", "load_truck", "trench", "grade", "stockpile"]
    description: str
    zone: str | None = None


class Weather(BaseModel):
    temp_c: float
    rain_mm: float = Field(ge=0)
    wind_kph: float = Field(ge=0)


class ShiftContext(BaseModel):
    """Everything the shadow engine needs to simulate a shift before it starts."""

    shift_id: int
    operator_id: int
    experience_years: float = Field(ge=0)
    machine_kind: Literal["excavator", "wheel_loader"]
    ground: Literal["dry", "wet", "muddy"]
    weather: Weather
    start_hour: float = Field(default=7.0, ge=0, lt=24)
    tasks: list[PlannedTask] = Field(min_length=1)


class ShadowTask(BaseModel):
    seq: int = Field(ge=1)
    task_type: str
    description: str
    duration_min: QuantileRange
    start_min: float = Field(ge=0, description="expected start, minutes from shift start")
    expected_idle_min: float = Field(ge=0)
    expected_fuel_l: float = Field(ge=0)
    risk_score: float | None = Field(default=None, ge=0, le=1)
    status: TaskStatus = TaskStatus.pending


class ShadowTimeline(BaseModel):
    shift_id: int
    tasks: list[ShadowTask]
    total_min: QuantileRange
    risk_points: list[str] = Field(default_factory=list)


# --- telemetry ------------------------------------------------------------


class TelemetryFrame(ORMModel):
    shift_id: int
    machine_id: int
    minute: int = Field(ge=0)
    lat: float
    lon: float
    engine_on: bool
    seatbelt: bool
    idle: bool
    fuel_rate_lph: float = Field(ge=0)
    speed_kph: float = Field(ge=0)
    load_pct: float = Field(ge=0, le=100)
    task_seq: int | None = None


# --- agent outputs (also used as LLM structured-output schemas) ----------


class Briefing(BaseModel):
    """Planner's pre-shift briefing."""

    headline: str
    key_risks: list[str]
    focus_tip: str


class Replan(BaseModel):
    """Dispatcher's reordered task list with a one-line reason."""

    new_order: list[int] = Field(description="task seq numbers in the new order")
    explanation: str = Field(max_length=200)


class IncidentReport(BaseModel):
    """Scribe's structured incident report built from an operator voice note."""

    category: Literal["ground", "equipment", "near_miss", "injury", "environment", "other"]
    summary: str
    severity: Severity
    hazard_kind: str | None = Field(
        default=None, description="short slug if this should become a site hazard pin"
    )
    actions_taken: list[str] = Field(default_factory=list)


# --- REST shapes ----------------------------------------------------------


class AlertOut(ORMModel):
    id: int
    shift_id: int
    minute: int
    kind: AlertKind
    severity: Severity
    message: str
    acknowledged: bool
    created_at: datetime


class IncidentCreate(BaseModel):
    shift_id: int
    minute: int = Field(ge=0)
    transcript: str = Field(min_length=1)
    lat: float | None = None
    lon: float | None = None


class IncidentOut(ORMModel):
    id: int
    shift_id: int
    minute: int
    transcript: str
    report: IncidentReport
    lat: float | None
    lon: float | None
    created_at: datetime


class HazardPinOut(ORMModel):
    id: int
    kind: str
    description: str
    lat: float
    lon: float
    radius_m: float
    confidence: float = Field(ge=0, le=1)
    active: bool
    last_confirmed_at: datetime


class ChatRequest(BaseModel):
    shift_id: int | None = None
    message: str = Field(min_length=1, max_length=2000)


class ChatAnswer(BaseModel):
    """Assistant structured output."""

    answer: str
    sources: list[str] = Field(default_factory=list)
    escalate_to_supervisor: bool = False


class BookingCreate(BaseModel):
    operator_id: int
    topic: str
    slot_start: datetime


class BookingOut(ORMModel):
    id: int
    operator_id: int
    instructor: str
    topic: str
    slot_start: datetime
    status: str


# --- WebSocket messages ---------------------------------------------------


class WsTelemetry(BaseModel):
    type: Literal["telemetry"] = "telemetry"
    frame: TelemetryFrame


class WsShadowDelta(BaseModel):
    type: Literal["shadow_delta"] = "shadow_delta"
    minute: int
    delta_min: float = Field(description="positive = ahead of shadow, negative = behind")


class WsAlert(BaseModel):
    type: Literal["alert"] = "alert"
    alert: AlertOut


class WsReplan(BaseModel):
    type: Literal["replan"] = "replan"
    minute: int
    replan: Replan


class WsHazardWarning(BaseModel):
    type: Literal["hazard_warning"] = "hazard_warning"
    machine_id: int
    pin: HazardPinOut
    distance_m: float = Field(ge=0)


class WsIncidentLogged(BaseModel):
    type: Literal["incident_logged"] = "incident_logged"
    incident: IncidentOut


class WsFatigue(BaseModel):
    type: Literal["fatigue"] = "fatigue"
    minute: int
    score: float = Field(ge=0, le=1)
    factors: dict[str, float]


class WsReplayStatus(BaseModel):
    type: Literal["replay_status"] = "replay_status"
    state: Literal["started", "paused", "finished"]
    minute: int


WsMessage = Annotated[
    WsTelemetry
    | WsShadowDelta
    | WsAlert
    | WsReplan
    | WsHazardWarning
    | WsIncidentLogged
    | WsFatigue
    | WsReplayStatus,
    Field(discriminator="type"),
]

_ws_adapter: TypeAdapter[WsMessage] = TypeAdapter(WsMessage)


def parse_ws_message(raw: str | bytes | dict) -> WsMessage:
    if isinstance(raw, dict):
        return _ws_adapter.validate_python(raw)
    return _ws_adapter.validate_json(raw)
