"""Coach: personalised training recommendations from the operator's recorded behaviour.

Scoring is deterministic: shift alerts, incidents, and practice results add weight to the
lessons that address them; lessons the operator has since passed count for less. The LLM only
writes a short encouraging note about the top picks, with a template fallback.
"""

from __future__ import annotations

import json
from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import training
from app.db import Alert, Incident, Shift
from app.llm import LLMError, get_llm

ALERT_WEIGHTS: dict[str, tuple[str, float, str]] = {
    # alert kind -> (lesson, weight, reason)
    "seatbelt": ("seatbelt", 3.0, "engine ran with the seatbelt unbuckled"),
    "idle_deviation": ("idle-fuel", 2.0, "a long unplanned idle"),
    "cycle_deviation": ("joystick", 2.0, "fell well behind the shadow plan"),
    "fatigue": ("fatigue", 2.0, "fatigue built up late in the shift"),
    "fuel_deviation": ("idle-fuel", 1.0, "fuel burn above the plan"),
    "hazard_proximity": ("soft-ground", 1.0, "came close to a reported hazard"),
}
INCIDENT_WEIGHTS: dict[str, tuple[str, float]] = {
    "ground": ("soft-ground", 3.0),
    "near_miss": ("emergencies", 3.0),
    "injury": ("emergencies", 3.0),
    "equipment": ("walkaround", 2.0),
    "environment": ("emergencies", 1.0),
}
PRACTICE_LESSONS = {
    "sim:dig": "joystick",
    "sim:reach": "loading",
    "sim:grade": "idle-fuel",
    "walkaround:leak": "walkaround",
    "drill:seatbelt": "seatbelt",
    "drill:idle_deviation": "idle-fuel",
    "drill:cycle_deviation": "joystick",
    "drill:fatigue": "fatigue",
    "drill:incident": "soft-ground",
}
PRACTICE_PASS = 0.6
PASSED_DISCOUNT = 0.5  # passing the quiz halves the weight: learned, still worth a refresher
INSTRUCTOR_AT = 3.0

SYSTEM_PROMPT = """You are a friendly equipment-operator coach. In 2 short sentences, tell the
operator which lessons to do next and why, using only the reasons given. Encouraging, specific,
no jargon, no blame."""


class Recommendation(BaseModel):
    lesson_id: str
    title: str
    weight: float
    reasons: list[str]
    practice: str | None


class CoachNote(BaseModel):
    note: str


class CoachAdvice(BaseModel):
    recommendations: list[Recommendation]
    note: str
    suggest_instructor: str | None  # lesson title to book an instructor for


def _events(db: Session, operator_id: int) -> tuple[list[Alert], list[Incident]]:
    shift_ids = select(Shift.id).where(Shift.operator_id == operator_id)
    alerts = list(db.scalars(select(Alert).where(Alert.shift_id.in_(shift_ids))))
    incidents = list(db.scalars(select(Incident).where(Incident.shift_id.in_(shift_ids))))
    return alerts, incidents


def score_lessons(db: Session, operator_id: int) -> list[Recommendation]:
    weights: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)

    def add(lesson: str, weight: float, reason: str) -> None:
        weights[lesson] += weight
        if reason not in reasons[lesson]:
            reasons[lesson].append(reason)

    alerts, incidents = _events(db, operator_id)
    for alert in alerts:
        if alert.kind in ALERT_WEIGHTS:
            lesson, weight, reason = ALERT_WEIGHTS[alert.kind]
            add(lesson, weight, reason)
    for incident in incidents:
        category = incident.report.get("category", "other")
        if category in INCIDENT_WEIGHTS:
            lesson, weight = INCIDENT_WEIGHTS[category]
            add(lesson, weight, f"reported: {incident.report.get('summary', category)}")

    best = training.best_scores(db, operator_id)
    for activity, lesson in PRACTICE_LESSONS.items():
        if activity in best and best[activity] < PRACTICE_PASS:
            add(lesson, 1.0, f"low score on {activity.replace(':', ' ')} practice")
    for lesson in list(weights):
        if best.get(lesson, 0.0) >= training.PASS_SCORE:
            weights[lesson] *= PASSED_DISCOUNT

    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        Recommendation(
            lesson_id=lesson,
            title=training.LESSONS[lesson].title,
            weight=round(weight, 2),
            reasons=reasons[lesson],
            practice=training.LESSONS[lesson].practice,
        )
        for lesson, weight in ranked
        if weight > 0
    ]


def template_note(recs: list[Recommendation]) -> str:
    if not recs:
        return "Clean shift. Keep it up, and try a simulator task to stay sharp."
    top = recs[0]
    text = f"Start with {top.title.lower()}: {top.reasons[0]}."
    if len(recs) > 1:
        text += f" Then {recs[1].title.lower()}."
    return text


def advise(db: Session, operator_id: int, top_n: int = 3) -> CoachAdvice:
    recs = score_lessons(db, operator_id)[:top_n]
    best = training.best_scores(db, operator_id)
    instructor = next(
        (
            r.title
            for r in recs
            if r.weight >= INSTRUCTOR_AT and best.get(r.lesson_id, 0.0) < training.PASS_SCORE
        ),
        None,
    )
    if not recs:
        note = template_note(recs)
    else:
        facts = [{"lesson": r.title, "because": r.reasons} for r in recs]
        try:
            note = get_llm().structured(SYSTEM_PROMPT, json.dumps(facts), CoachNote).note
        except LLMError:
            note = template_note(recs)
    return CoachAdvice(recommendations=recs, note=note, suggest_instructor=instructor)
