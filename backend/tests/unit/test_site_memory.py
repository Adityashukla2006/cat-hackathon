from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import HazardPin, make_engine, make_session_factory
from app.geo import offset
from app.main import create_app
from app.replay import demo_context, demo_frames
from app.runtime import ShiftRuntime
from app.schemas import AlertKind, TelemetryFrame, WsAlert, WsHazardPin, WsHazardWarning
from app.site_memory import (
    EXPIRE_BELOW,
    WARN_BUFFER_M,
    ProximityWatch,
    active_pins,
    confidence,
    pin_out,
    record_hazard,
)
from data.generate import DEMO_SCRIPT, generate

T0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
SPOT = (40.695, -89.589)


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


def _pin(db, kind="soft_ground", at=T0, where=SPOT, machine_id=1):
    pin, _ = record_hazard(
        db,
        kind=kind,
        description="Soft ground.",
        lat=where[0],
        lon=where[1],
        at=at,
        machine_id=machine_id,
    )
    return pin


def _frame(machine_id, lat, lon, minute=0):
    return TelemetryFrame(
        shift_id=1,
        machine_id=machine_id,
        minute=minute,
        lat=lat,
        lon=lon,
        engine_on=True,
        seatbelt=True,
        idle=False,
        fuel_rate_lph=10,
        speed_kph=10,
        load_pct=40,
    )


def test_confidence_halves_every_half_life(db_session):
    pin = _pin(db_session)
    assert confidence(pin, T0) == 1.0
    assert confidence(pin, T0 + timedelta(hours=12)) == 0.5
    assert confidence(pin, T0 + timedelta(hours=24)) == 0.25


def test_faded_pins_expire_and_a_new_report_makes_a_new_pin(db_session):
    pin = _pin(db_session)
    later = T0 + timedelta(hours=30)
    assert confidence(pin, later) < EXPIRE_BELOW
    assert active_pins(db_session, later) == []
    assert db_session.get(HazardPin, pin.id).active is False
    revived = _pin(db_session, at=later)
    assert revived.id != pin.id
    assert [p.id for p in active_pins(db_session, later)] == [revived.id]


def test_nearby_report_of_same_kind_reconfirms(db_session):
    first = _pin(db_session)
    near = offset(*SPOT, 10, 5)
    six_hours = T0 + timedelta(hours=6)
    again, created = record_hazard(
        db_session, kind="soft_ground", description="x", lat=near[0], lon=near[1], at=six_hours
    )
    assert (again.id, created) == (first.id, False)
    assert confidence(again, six_hours) == 1.0

    far = offset(*SPOT, 200, 0)
    _, created = record_hazard(
        db_session, kind="soft_ground", description="x", lat=far[0], lon=far[1], at=T0
    )
    assert created is True
    _, created = record_hazard(
        db_session, kind="spill", description="x", lat=SPOT[0], lon=SPOT[1], at=T0
    )
    assert created is True


def test_proximity_warns_once_per_approach_and_rearms(db_session):
    view = pin_out(_pin(db_session, machine_id=1), T0)
    watch = ProximityWatch()
    edge = view.radius_m + WARN_BUFFER_M
    far = offset(*SPOT, edge + 50, 0)
    close = offset(*SPOT, edge - 5, 0)
    assert watch.check(_frame(2, *far), [view]) == []
    hits = watch.check(_frame(2, *close), [view])
    assert len(hits) == 1 and hits[0][1] == pytest.approx(edge - 5, abs=0.5)
    assert watch.check(_frame(2, *SPOT), [view]) == []  # already warned
    watch.check(_frame(2, *far), [view])  # leaves, re-arms
    assert len(watch.check(_frame(2, *close), [view])) == 1
    assert watch.check(_frame(1, *SPOT), [view]) == []  # reporter isn't warned about its own pin


def test_demo_hazard_warns_second_machine_on_approach(demo, predictor, db_session):
    runtime = ShiftRuntime(db_session, demo, predictor.predict(demo_context(demo)))
    by_minute = defaultdict(list)
    for f in demo_frames(demo):
        by_minute[f.minute].append(f)
    out = [(m, msg) for m in sorted(by_minute) for msg in runtime.process_minute(m, by_minute[m])]

    pins = [(m, msg) for m, msg in out if isinstance(msg, WsHazardPin)]
    assert [m for m, _ in pins] == [DEMO_SCRIPT["incident_minute"]]
    assert pins[0][1].pin.kind == "soft_ground"

    warnings = [(m, msg) for m, msg in out if isinstance(msg, WsHazardWarning)]
    assert len(warnings) == 1
    minute, warning = warnings[0]
    lo, hi = DEMO_SCRIPT["second_machine_approach"]
    assert warning.machine_id == 2 and lo <= minute <= hi
    assert warning.distance_m > warning.pin.radius_m  # warned before entering the zone
    assert runtime.session.memory["hazard_zones"] == ["ramp"]

    own = [
        m for _, m in out if isinstance(m, WsAlert) and m.alert.kind == AlertKind.hazard_proximity
    ]
    assert own == []  # the reporting machine isn't warned about its own report


def test_replaying_the_demo_resets_its_own_pins_only(demo, db_session):
    other = _pin(db_session, kind="spill", where=offset(*SPOT, 500, 0))
    runtime = ShiftRuntime(db_session, demo, None)
    runtime.voice_note(
        DEMO_SCRIPT["incident_minute"],
        transcript=DEMO_SCRIPT["incident_transcript"],
        lat=SPOT[0],
        lon=SPOT[1],
    )
    assert len(db_session.scalars(select(HazardPin)).all()) == 2
    ShiftRuntime(db_session, demo, None)
    assert [p.id for p in db_session.scalars(select(HazardPin))] == [other.id]


def test_hazard_endpoints():
    app = create_app(make_engine("sqlite://"))
    with TestClient(app) as client:
        db = make_session_factory(app.state.engine)()
        pin = _pin(db, at=datetime.now(timezone.utc))
        db.close()
        assert [p["id"] for p in client.get("/hazards").json()] == [pin.id]
        assert client.post(f"/hazards/{pin.id}/confirm").json()["confidence"] == 1.0
        assert client.post(f"/hazards/{pin.id}/clear").json()["active"] is False
        assert client.get("/hazards").json() == []
        assert client.post("/hazards/999/confirm").status_code == 404
