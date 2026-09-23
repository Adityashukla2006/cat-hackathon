"""Living Site Memory: incidents become geofenced hazard pins that warn approaching machines
and fade unless someone reconfirms them. Deterministic, no LLM.

Confidence halves every HALF_LIFE_H hours since the last confirmation; a pin whose confidence
drops below EXPIRE_BELOW stops warning and is marked inactive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import HazardPin
from app.geo import distance_m
from app.schemas import HazardPinOut, TelemetryFrame

RADIUS_M = {"soft_ground": 30.0, "spill": 20.0, "overhead_line": 40.0}
DEFAULT_RADIUS_M = 25.0
HALF_LIFE_H = {"soft_ground": 12.0, "spill": 6.0, "overhead_line": 72.0}
DEFAULT_HALF_LIFE_H = 8.0
EXPIRE_BELOW = 0.2
WARN_BUFFER_M = 40.0  # warn this far before the pin's edge
REARM_EXTRA_M = 20.0  # must leave this much further before the same pin warns again


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def confidence(pin: HazardPin, now: datetime) -> float:
    hours = max((_aware(now) - _aware(pin.last_confirmed_at)).total_seconds() / 3600.0, 0.0)
    half_life = HALF_LIFE_H.get(pin.kind, DEFAULT_HALF_LIFE_H)
    return round(math.pow(0.5, hours / half_life), 3)


def pin_out(pin: HazardPin, now: datetime) -> HazardPinOut:
    conf = confidence(pin, now)
    return HazardPinOut(
        id=pin.id,
        kind=pin.kind,
        description=pin.description,
        lat=pin.lat,
        lon=pin.lon,
        radius_m=pin.radius_m,
        confidence=conf,
        active=pin.active and conf >= EXPIRE_BELOW,
        last_confirmed_at=pin.last_confirmed_at,
        reported_by_machine_id=pin.reported_by_machine_id,
    )


def active_pins(db: Session, now: datetime) -> list[HazardPinOut]:
    """Active pins with decayed confidence. Pins that have faded out are marked inactive."""
    out = []
    for pin in db.scalars(
        select(HazardPin).where(HazardPin.active.is_(True)).order_by(HazardPin.id)
    ):
        view = pin_out(pin, now)
        if view.active:
            out.append(view)
        else:
            pin.active = False
    db.commit()
    return out


def record_hazard(
    db: Session,
    *,
    kind: str,
    description: str,
    lat: float,
    lon: float,
    at: datetime,
    incident_id: int | None = None,
    machine_id: int | None = None,
) -> tuple[HazardPin, bool]:
    """Create a pin, or reconfirm an active pin of the same kind that already covers the spot.
    Returns (pin, created)."""
    for existing in db.scalars(
        select(HazardPin).where(HazardPin.active.is_(True), HazardPin.kind == kind)
    ):
        close = distance_m(existing.lat, existing.lon, lat, lon) <= existing.radius_m
        if close and pin_out(existing, at).active:
            reconfirm(db, existing, at)
            return existing, False
    pin = HazardPin(
        incident_id=incident_id,
        reported_by_machine_id=machine_id,
        kind=kind,
        description=description[:300],
        lat=lat,
        lon=lon,
        radius_m=RADIUS_M.get(kind, DEFAULT_RADIUS_M),
        confidence=1.0,
        created_at=at,
        last_confirmed_at=at,
        active=True,
    )
    db.add(pin)
    db.commit()
    return pin, True


def reconfirm(db: Session, pin: HazardPin, at: datetime) -> HazardPin:
    pin.last_confirmed_at = at
    pin.confidence = 1.0
    pin.active = True
    db.commit()
    return pin


def clear(db: Session, pin: HazardPin) -> HazardPin:
    pin.active = False
    db.commit()
    return pin


@dataclass
class ProximityWatch:
    """Remembers which machine has been warned about which pin, so each approach warns once."""

    warned: set[tuple[int, int]] = field(default_factory=set)

    def check(
        self, frame: TelemetryFrame, pins: list[HazardPinOut]
    ) -> list[tuple[HazardPinOut, float]]:
        hits = []
        for pin in pins:
            if not pin.active or pin.reported_by_machine_id == frame.machine_id:
                continue
            key = (frame.machine_id, pin.id)
            dist = distance_m(frame.lat, frame.lon, pin.lat, pin.lon)
            warn_at = pin.radius_m + WARN_BUFFER_M
            if dist <= warn_at and key not in self.warned:
                self.warned.add(key)
                hits.append((pin, round(dist, 1)))
            elif dist > warn_at + REARM_EXTRA_M:
                self.warned.discard(key)
        return hits
