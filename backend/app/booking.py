"""Instructor booking against a mocked calendar.

Each instructor teaches some lessons. Open slots are weekdays at fixed times, minus a few
seeded busy slots (deterministic, so the demo looks realistic) and anything already booked.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Booking

SLOT_TIMES = [time(8, 0), time(13, 0), time(15, 30)]
BUSY_SHARE = 0.35  # roughly a third of calendar slots are already taken


@dataclass(frozen=True)
class Instructor:
    name: str
    topics: frozenset[str]


INSTRUCTORS = [
    Instructor("Maria Lopez", frozenset({"seatbelt", "walkaround", "emergencies", "fatigue"})),
    Instructor("Tom Becker", frozenset({"soft-ground", "joystick", "loading"})),
    Instructor("Grace Chen", frozenset({"idle-fuel", "loading", "fatigue", "soft-ground"})),
]


class SlotTakenError(ValueError):
    pass


def teaches(topic: str) -> list[Instructor]:
    return [i for i in INSTRUCTORS if topic in i.topics]


def _seeded_busy(instructor: str, slot: datetime) -> bool:
    digest = hashlib.sha1(f"{instructor}|{slot.isoformat()}".encode()).digest()
    return digest[0] / 255 < BUSY_SHARE


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _booked(db: Session) -> set[tuple[str, datetime]]:
    rows = db.scalars(select(Booking).where(Booking.status == "confirmed"))
    return {(b.instructor, _as_utc(b.slot_start)) for b in rows}


def weekday_slots(start: date, days: int) -> list[datetime]:
    slots, day = [], start
    while len({s.date() for s in slots}) < days:
        if day.weekday() < 5:
            slots += [datetime.combine(day, t, tzinfo=timezone.utc) for t in SLOT_TIMES]
        day += timedelta(days=1)
    return slots


def open_slots(db: Session, topic: str, start: date, days: int = 5) -> list[tuple[str, datetime]]:
    """(instructor, slot) pairs free for this topic, earliest first."""
    booked = _booked(db)
    out = []
    for slot in weekday_slots(start, days):
        for instructor in teaches(topic):
            key = (instructor.name, slot)
            if key not in booked and not _seeded_busy(instructor.name, slot):
                out.append(key)
    return sorted(out, key=lambda pair: (pair[1], pair[0]))


def book(
    db: Session,
    operator_id: int,
    topic: str,
    slot_start: datetime,
    instructor: str | None = None,
) -> Booking:
    slot_start = _as_utc(slot_start)
    candidates = [
        name
        for name, slot in open_slots(db, topic, slot_start.date(), days=1)
        if slot == slot_start and (instructor is None or name == instructor)
    ]
    if not candidates:
        raise SlotTakenError("no instructor for that topic is free at that time")
    row = Booking(
        operator_id=operator_id, instructor=candidates[0], topic=topic, slot_start=slot_start
    )
    db.add(row)
    db.commit()
    return row


def cancel(db: Session, booking: Booking) -> Booking:
    booking.status = "cancelled"
    db.commit()
    return booking
