from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import booking, training
from app.db import Operator, make_engine, make_session_factory
from app.main import create_app

MONDAY = date(2026, 9, 28)


@pytest.fixture
def client():
    app = create_app(make_engine("sqlite://"))
    with TestClient(app) as c:
        db = make_session_factory(app.state.engine)()
        if db.get(Operator, 1) is None:
            db.add(Operator(id=1, name="Sam Rivera", experience_years=2.5))
            db.commit()
        db.close()
        yield c


def test_every_lesson_has_an_instructor():
    for lesson_id in training.LESSONS:
        assert booking.teaches(lesson_id), lesson_id


def test_weekday_slots_skip_weekends():
    slots = booking.weekday_slots(date(2026, 9, 26), days=2)  # Saturday start
    assert {s.date() for s in slots} == {date(2026, 9, 28), date(2026, 9, 29)}
    assert len(slots) == 2 * len(booking.SLOT_TIMES)


def test_open_slots_are_deterministic_and_partly_busy(db_session):
    first = booking.open_slots(db_session, "seatbelt", MONDAY)
    assert first == booking.open_slots(db_session, "seatbelt", MONDAY)
    total = 5 * len(booking.SLOT_TIMES) * len(booking.teaches("seatbelt"))
    assert 0 < len(first) < total
    assert all(name == "Maria Lopez" for name, _ in first)
    assert first == sorted(first, key=lambda p: (p[1], p[0]))


def test_booking_takes_the_slot(db_session):
    db_session.add(Operator(id=1, name="x", experience_years=1))
    db_session.commit()
    name, slot = booking.open_slots(db_session, "soft-ground", MONDAY)[0]
    row = booking.book(db_session, 1, "soft-ground", slot)
    assert row.instructor == name and row.status == "confirmed"
    assert (name, slot) not in booking.open_slots(db_session, "soft-ground", MONDAY)
    others = [n for n, s in booking.open_slots(db_session, "soft-ground", MONDAY) if s == slot]
    if not others:
        with pytest.raises(booking.SlotTakenError):
            booking.book(db_session, 1, "soft-ground", slot)
    booking.cancel(db_session, row)
    assert (name, slot) in booking.open_slots(db_session, "soft-ground", MONDAY)


def test_booking_a_time_nobody_offers_fails(db_session):
    midnight = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(booking.SlotTakenError):
        booking.book(db_session, 1, "seatbelt", midnight)


def test_booking_endpoints(client):
    slots = client.get(
        "/instructors/slots", params={"topic": "seatbelt", "start": MONDAY.isoformat(), "days": 2}
    ).json()
    assert slots and {s["instructor"] for s in slots} == {"Maria Lopez"}
    first = slots[0]
    created = client.post(
        "/bookings",
        json={"operator_id": 1, "topic": "seatbelt", "slot_start": first["slot_start"]},
    )
    assert created.status_code == 201
    booked = created.json()
    assert booked["instructor"] == "Maria Lopez"

    again = client.post(
        "/bookings",
        json={"operator_id": 1, "topic": "seatbelt", "slot_start": first["slot_start"]},
    )
    assert again.status_code == 409
    mine = client.get("/operators/1/bookings").json()
    assert [b["id"] for b in mine] == [booked["id"]]

    assert client.post(f"/bookings/{booked['id']}/cancel").json()["status"] == "cancelled"
    assert client.get("/operators/1/bookings").json() == []
    assert client.get("/instructors/slots", params={"topic": "nope"}).status_code == 404
    unknown_op = client.post(
        "/bookings", json={"operator_id": 9, "topic": "seatbelt", "slot_start": first["slot_start"]}
    )
    assert unknown_op.status_code == 404
