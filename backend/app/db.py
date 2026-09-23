from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    experience_years: Mapped[float] = mapped_column(Float, default=0.0)
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list)

    shifts: Mapped[list[Shift]] = relationship(back_populates="operator")


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    model: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(40))


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="planned")
    weather: Mapped[dict] = mapped_column(JSON, default=dict)
    site_conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    briefing: Mapped[str | None] = mapped_column(Text, nullable=True)

    operator: Mapped[Operator] = relationship(back_populates="shifts")
    machine: Mapped[Machine] = relationship()
    tasks: Mapped[list[ShiftTask]] = relationship(
        back_populates="shift", order_by="ShiftTask.seq", cascade="all, delete-orphan"
    )
    alerts: Mapped[list[Alert]] = relationship(back_populates="shift", cascade="all, delete-orphan")
    incidents: Mapped[list[Incident]] = relationship(
        back_populates="shift", cascade="all, delete-orphan"
    )


class ShiftTask(Base):
    __tablename__ = "shift_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"))
    seq: Mapped[int] = mapped_column(Integer)
    task_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200))
    p10_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    p90_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    shift: Mapped[Shift] = relationship(back_populates="tasks")


class TelemetryPoint(Base):
    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"))
    minute: Mapped[int] = mapped_column(Integer, index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    engine_on: Mapped[bool] = mapped_column(Boolean)
    seatbelt: Mapped[bool] = mapped_column(Boolean)
    idle: Mapped[bool] = mapped_column(Boolean)
    fuel_rate_lph: Mapped[float] = mapped_column(Float)
    speed_kph: Mapped[float] = mapped_column(Float)
    load_pct: Mapped[float] = mapped_column(Float)
    task_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    minute: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(String(300))
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    shift: Mapped[Shift] = relationship(back_populates="alerts")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    minute: Mapped[int] = mapped_column(Integer)
    transcript: Mapped[str] = mapped_column(Text)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    shift: Mapped[Shift] = relationship(back_populates="incidents")


class HazardPin(Base):
    __tablename__ = "hazard_pins"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    reported_by_machine_id: Mapped[int | None] = mapped_column(
        ForeignKey("machines.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(300))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float, default=30.0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LessonProgress(Base):
    __tablename__ = "lesson_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)
    lesson_id: Mapped[str] = mapped_column(String(60))
    quiz_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)
    instructor: Mapped[str] = mapped_column(String(120))
    topic: Mapped[str] = mapped_column(String(120))
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="confirmed")


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session bound to the configured database."""
    session = make_session_factory(get_engine())()
    try:
        yield session
    finally:
        session.close()
