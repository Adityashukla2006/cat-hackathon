"""Learn-from-your-shift drills: what happened on the operator's shift becomes a short drill.

Each alert or incident maps to a drill template (lesson, practice task, a fallback question).
The LLM rewrites the scenario and question around the real moment; the answer it marks must
point at one of its options, otherwise the template is used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Alert, Incident, Shift
from app.llm import LLMError, get_llm

SYSTEM_PROMPT = """You write a one-question safety drill for a heavy-equipment operator, based on
something that really happened on their shift. Use only the facts given.
scenario: 1-2 sentences replaying the moment in second person ("At 07:02 you...").
question: what should you do / what was the risk.
options: exactly 3 short options, one correct.
answer: index of the correct option. explanation: one sentence, consistent with the lesson."""


class DrillContent(BaseModel):
    scenario: str
    question: str
    options: list[str] = Field(min_length=3, max_length=3)
    answer: int
    explanation: str

    @model_validator(mode="after")
    def _answer_in_range(self) -> DrillContent:
        if not 0 <= self.answer < len(self.options):
            raise ValueError("answer must index one of the options")
        return self


@dataclass(frozen=True)
class DrillTemplate:
    kind: str
    title: str
    lesson_id: str
    practice: str | None
    fallback: DrillContent


TEMPLATES: dict[str, DrillTemplate] = {
    "seatbelt": DrillTemplate(
        "seatbelt",
        "Seatbelt before start",
        "seatbelt",
        None,
        DrillContent(
            scenario="At {clock} your engine was running with the seatbelt unbuckled.",
            question="What's the right order when you climb in?",
            options=[
                "Start the engine, then buckle up",
                "Buckle up, then start the engine",
                "Buckle up only before travelling",
            ],
            answer=1,
            explanation="Buckle up before the engine starts, every time.",
        ),
    ),
    "idle_deviation": DrillTemplate(
        "idle_deviation",
        "Long idle wait",
        "idle-fuel",
        "grade",
        DrillContent(
            scenario="At {clock} you sat idling far longer than planned.",
            question="You're stuck waiting for more than a few minutes. What do you do?",
            options=[
                "Keep the engine at working revs",
                "Idle down and tell dispatch you're waiting",
                "Start a different task without telling anyone",
            ],
            answer=1,
            explanation="Idle down and let dispatch reshuffle the work.",
        ),
    ),
    "cycle_deviation": DrillTemplate(
        "cycle_deviation",
        "Falling behind plan",
        "joystick",
        "dig",
        DrillContent(
            scenario="At {clock} you were well behind the shadow plan.",
            question="What's the best way to get cycles back on pace?",
            options=[
                "Full-lever jerks to move faster",
                "Smooth, combined movements and a short swing",
                "Skip the swing-area check",
            ],
            answer=1,
            explanation="Smooth, combined movements are faster and safer than jerky ones.",
        ),
    ),
    "fatigue": DrillTemplate(
        "fatigue",
        "Spotting fatigue",
        "fatigue",
        None,
        DrillContent(
            scenario="At {clock} your cycles slowed and pauses increased: signs of fatigue.",
            question="You notice you're getting tired late in the shift. What do you do?",
            options=[
                "Push on to finish",
                "Park safely, take a break, tell your supervisor",
                "Work faster to finish sooner",
            ],
            answer=1,
            explanation="Park safely and take a break. It's always OK to stop.",
        ),
    ),
    "incident": DrillTemplate(
        "incident",
        "What you reported",
        "soft-ground",
        None,
        DrillContent(
            scenario="At {clock} you reported: {detail}",
            question="Your track starts to sink near an edge. What's the first step?",
            options=[
                "Raise the bucket and keep digging",
                "Stop, keep the bucket low, and back out onto firm ground",
                "Turn across the slope",
            ],
            answer=1,
            explanation="Stop, keep the bucket low, back out the way you came.",
        ),
    ),
}


class Drill(BaseModel):
    id: str
    kind: str
    minute: int
    title: str
    lesson_id: str
    practice: str | None
    content: DrillContent
    source: str  # "llm" or "template"


def _clock(started_at: datetime, minute: int) -> str:
    return (started_at + timedelta(minutes=minute)).strftime("%H:%M")


def shift_moments(db: Session, shift_id: int) -> list[tuple[str, int, str]]:
    """(kind, minute, detail) for the first alert of each drill-worthy kind, plus incidents."""
    moments: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for alert in db.scalars(
        select(Alert).where(Alert.shift_id == shift_id).order_by(Alert.minute, Alert.id)
    ):
        if alert.kind in TEMPLATES and alert.kind not in seen:
            seen.add(alert.kind)
            moments.append((alert.kind, alert.minute, alert.message))
    for incident in db.scalars(select(Incident).where(Incident.shift_id == shift_id)):
        summary = incident.report.get("summary") or incident.transcript
        moments.append(("incident", incident.minute, summary))
    return sorted(moments, key=lambda m: m[1])


def build_drill(kind: str, minute: int, detail: str, started_at: datetime) -> Drill:
    template = TEMPLATES[kind]
    clock = _clock(started_at, minute)
    fallback = template.fallback.model_copy(
        update={"scenario": template.fallback.scenario.format(clock=clock, detail=detail)}
    )
    facts = {"time": clock, "what_happened": detail, "lesson_answer": fallback.explanation}
    try:
        content = get_llm().structured(SYSTEM_PROMPT, json.dumps(facts), DrillContent)
        source = "llm"
    except LLMError:
        content, source = fallback, "template"
    return Drill(
        id=f"{kind}-{minute}",
        kind=kind,
        minute=minute,
        title=template.title,
        lesson_id=template.lesson_id,
        practice=template.practice,
        content=content,
        source=source,
    )


def drills_for_shift(db: Session, shift_id: int) -> list[Drill]:
    shift = db.get(Shift, shift_id)
    if shift is None:
        return []
    return [
        build_drill(kind, minute, detail, shift.started_at)
        for kind, minute, detail in shift_moments(db, shift_id)
    ]
