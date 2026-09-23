"""Handover briefing: what the next shift needs to know, from what this shift recorded.

The facts (tasks, incidents, hazards, open alerts) are gathered deterministically; the LLM only
phrases them, with a template fallback. Hazards always come straight from site memory.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import ShiftSession
from app.db import Alert, Incident, Shift
from app.llm import LLMError, get_llm
from app.site_memory import HazardPinOut, active_pins

SYSTEM_PROMPT = """You write the end-of-shift handover for the next heavy-equipment operator and
their supervisor. Use only the facts provided; no new numbers or hazards.
headline: one factual sentence: how many tasks were done, minutes vs plan (minutes_vs_shadow,
negative means behind), and the incident count. No judgements like "went well".
carry_over: unfinished work, in the order it should be done, one short item each.
watch_outs: at most 3 short safety notes for the next shift, hazards first, each written as an
instruction for the next operator (not a copy of an alert)."""


class HandoverText(BaseModel):
    headline: str
    carry_over: list[str]
    watch_outs: list[str]


class Handover(BaseModel):
    shift_id: int
    headline: str
    done: list[str]
    carry_over: list[str]
    watch_outs: list[str]
    hazards: list[HazardPinOut]
    incidents: list[str]
    open_alerts: list[str]
    minutes_vs_shadow: float | None
    source: str


def gather_facts(
    db: Session, shift_id: int, now: datetime, session: ShiftSession | None = None
) -> dict[str, Any]:
    shift = db.get(Shift, shift_id)
    if shift is None:
        raise LookupError(f"shift {shift_id} not found")
    order = session.task_order if session else [t.seq for t in shift.tasks]
    tasks = {t.seq: t for t in shift.tasks}
    done = [tasks[s] for s in order if tasks[s].status == "done"]
    todo = [tasks[s] for s in order if tasks[s].status != "done"]
    alerts = list(
        db.scalars(select(Alert).where(Alert.shift_id == shift_id).order_by(Alert.minute))
    )
    incidents = list(
        db.scalars(select(Incident).where(Incident.shift_id == shift_id).order_by(Incident.minute))
    )
    fatigue = session.memory.get("last_fatigue") if session else None
    return {
        "shift_id": shift_id,
        "done": [
            f"{t.description} ({t.actual_min:.0f} min vs {t.p50_min:.0f} planned)"
            if t.actual_min is not None and t.p50_min is not None
            else t.description
            for t in done
        ],
        "carry_over": [
            f"{t.description}{' (in progress)' if t.status == 'active' else ''}" for t in todo
        ],
        "incidents": [i.report.get("summary", i.transcript) for i in incidents],
        "open_alerts": [a.message for a in alerts if not a.acknowledged],
        "alert_kinds": sorted({a.kind for a in alerts}),
        "minutes_vs_shadow": session.memory.get("last_delta") if session else None,
        "fatigue_score": fatigue.score if fatigue else None,
        "hazards": active_pins(db, now),
    }


def template_text(facts: dict[str, Any]) -> HandoverText:
    delta = facts["minutes_vs_shadow"]
    pace = ""
    if delta is not None:
        pace = f", {abs(delta):.0f} min {'ahead of' if delta >= 0 else 'behind'} plan"
    headline = f"{len(facts['done'])} tasks done{pace}."
    watch = [f"{h.description} ({h.confidence:.0%} confidence)" for h in facts["hazards"]]
    if "fatigue" in facts["alert_kinds"]:
        watch.append("Fatigue built up late in the shift; plan breaks.")
    if "seatbelt" in facts["alert_kinds"]:
        watch.append("Seatbelt was unbuckled at start-up; buckle up before the engine starts.")
    return HandoverText(headline=headline, carry_over=facts["carry_over"], watch_outs=watch[:3])


def build_handover(
    db: Session, shift_id: int, now: datetime, session: ShiftSession | None = None
) -> Handover:
    facts = gather_facts(db, shift_id, now, session)
    prompt_facts = {**facts, "hazards": [h.description for h in facts["hazards"]]}
    try:
        text = get_llm().structured(SYSTEM_PROMPT, json.dumps(prompt_facts), HandoverText)
        source = "llm"
    except LLMError:
        text, source = template_text(facts), "template"
    return Handover(
        shift_id=shift_id,
        headline=text.headline,
        done=facts["done"],
        carry_over=text.carry_over,
        watch_outs=text.watch_outs,
        hazards=facts["hazards"],
        incidents=facts["incidents"],
        open_alerts=facts["open_alerts"],
        minutes_vs_shadow=facts["minutes_vs_shadow"],
        source=source,
    )
