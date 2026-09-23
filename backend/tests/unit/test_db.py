from datetime import datetime, timezone

from sqlalchemy import inspect

from app.db import (
    Alert,
    Base,
    HazardPin,
    Incident,
    Machine,
    Operator,
    Shift,
    ShiftTask,
    TelemetryPoint,
)


def _shift(db_session) -> Shift:
    op = Operator(name="Sam Rivera", experience_years=2.5, certifications=["excavator"])
    machine = Machine(name="EX-01", model="CAT 320", kind="excavator")
    shift = Shift(
        operator=op,
        machine=machine,
        started_at=datetime(2026, 9, 23, 7, 0, tzinfo=timezone.utc),
        weather={"temp_c": 18, "rain_mm": 2.0},
    )
    db_session.add(shift)
    db_session.commit()
    return shift


def test_all_tables_created(db_session):
    tables = set(inspect(db_session.get_bind()).get_table_names())
    assert tables == set(Base.metadata.tables)
    assert {"shifts", "telemetry", "hazard_pins", "incidents", "bookings"} <= tables


def test_shift_tasks_ordered_by_seq(db_session):
    shift = _shift(db_session)
    shift.tasks.append(ShiftTask(seq=2, task_type="load", description="Load trucks"))
    shift.tasks.append(ShiftTask(seq=1, task_type="dig", description="Dig trench"))
    db_session.commit()
    db_session.expire_all()
    loaded = db_session.get(Shift, shift.id)
    assert [t.seq for t in loaded.tasks] == [1, 2]
    assert loaded.operator.certifications == ["excavator"]
    assert loaded.weather["rain_mm"] == 2.0


def test_alerts_incidents_and_telemetry_link_to_shift(db_session):
    shift = _shift(db_session)
    db_session.add_all(
        [
            Alert(
                shift_id=shift.id, minute=12, kind="seatbelt", severity="high", message="Buckle up"
            ),
            Incident(
                shift_id=shift.id, minute=95, transcript="soft ground", report={"type": "ground"}
            ),
            TelemetryPoint(
                shift_id=shift.id,
                machine_id=shift.machine_id,
                minute=0,
                lat=1.0,
                lon=2.0,
                engine_on=True,
                seatbelt=False,
                idle=True,
                fuel_rate_lph=4.0,
                speed_kph=0.0,
                load_pct=0.0,
            ),
        ]
    )
    db_session.commit()
    db_session.refresh(shift)
    assert shift.alerts[0].acknowledged is False
    assert shift.alerts[0].created_at is not None
    assert shift.incidents[0].report == {"type": "ground"}


def test_hazard_pin_defaults(db_session):
    pin = HazardPin(kind="soft_ground", description="Soft ground near ramp", lat=1.0, lon=2.0)
    db_session.add(pin)
    db_session.commit()
    assert pin.active is True
    assert pin.confidence == 1.0
    assert pin.radius_m == 30.0
