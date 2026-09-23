from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.db import Alert
from app.schemas import (
    AlertOut,
    IncidentReport,
    QuantileRange,
    Replan,
    TelemetryFrame,
    WsAlert,
    WsShadowDelta,
    WsTelemetry,
    parse_ws_message,
)


def _frame(**overrides) -> TelemetryFrame:
    data = dict(
        shift_id=1,
        machine_id=1,
        minute=5,
        lat=1.0,
        lon=2.0,
        engine_on=True,
        seatbelt=True,
        idle=False,
        fuel_rate_lph=12.0,
        speed_kph=3.0,
        load_pct=55.0,
    )
    data.update(overrides)
    return TelemetryFrame(**data)


def test_quantile_range_rejects_unordered():
    assert QuantileRange(p10=1, p50=2, p90=3).p50 == 2
    with pytest.raises(ValidationError):
        QuantileRange(p10=5, p50=2, p90=3)


def test_telemetry_frame_bounds():
    with pytest.raises(ValidationError):
        _frame(load_pct=120)
    with pytest.raises(ValidationError):
        _frame(minute=-1)


def test_ws_messages_round_trip_through_discriminator():
    for msg in (WsTelemetry(frame=_frame()), WsShadowDelta(minute=10, delta_min=-2.5)):
        parsed = parse_ws_message(msg.model_dump_json())
        assert type(parsed) is type(msg)
        assert parsed == msg


def test_ws_unknown_type_rejected():
    with pytest.raises(ValidationError):
        parse_ws_message({"type": "nope"})


def test_alert_out_from_orm():
    row = Alert(
        id=3,
        shift_id=1,
        minute=12,
        kind="seatbelt",
        severity="critical",
        message="Buckle up",
        acknowledged=False,
        created_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    out = AlertOut.model_validate(row)
    assert out.kind.value == "seatbelt"
    assert parse_ws_message(WsAlert(alert=out).model_dump()).alert.id == 3


def test_llm_schemas_have_constraints():
    with pytest.raises(ValidationError):
        IncidentReport(category="alien", summary="x", severity="info")
    with pytest.raises(ValidationError):
        Replan(new_order=[1, 2], explanation="x" * 201)
