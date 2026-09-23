"""Assistant: the operator's in-cab chatbot.

Tools (plain functions) gather context: live shift status, nearby hazards, and guide excerpts.
The LLM writes one short structured answer from that context. Deterministic rails around it:
  - a safety question the guides don't cover gets "stop and contact your supervisor", with no
    LLM call at all
  - cited sources must be guide sections that were actually retrieved
  - a safety answer without a valid guide source is replaced by the escalation
  - if the LLM is down, the answer is built from the tools alone
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.state import ShiftSession
from app.geo import distance_m
from app.llm import LLMError, get_llm
from app.retrieval import GuideIndex, Hit
from app.schemas import ChatAnswer

ESCALATION = (
    "The guides don't cover that. Stop work safely and contact your supervisor before you continue."
)
NO_SHIFT = "There's no live shift running right now."
SAFETY_TERMS = re.compile(
    r"\b(safe\w*|danger\w*|hazard\w*|seat ?belt|belt|soft|sink\w*|sank|edge|slope|ramp|trench"
    r"|tip\w*|roll\w*|fire|smoke|power ?line|electric\w*|leak\w*|hydraulic|injur\w*|hurt"
    r"|emergenc\w*|tired|fatigue\w*|drows\w*|break|walkaround|inspect\w*|swing|people|"
    r"reverse|reversing|brake|lockout)\b",
    re.IGNORECASE,
)
STATUS_TERMS = re.compile(
    r"\b(behind|ahead|schedule|plan|next|task|shift|minutes?|late|progress|fuel|load|alerts?"
    r"|replan|order|where|nearest|how far|score)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You are the in-cab assistant for a heavy-equipment operator.
Answer in at most 3 short sentences, plain words, readable at a glance.
Questions about the shift: use only LIVE_SHIFT and HAZARDS. Never invent numbers.
Safety or how-to questions: use only GUIDE_EXCERPTS, and list the exact `source` strings you
used in `sources`. If the excerpts do not cover the question, set escalate_to_supervisor=true
and tell the operator to stop and contact their supervisor. Never guess about safety."""


# --- tools -----------------------------------------------------------------


def shift_status(session: ShiftSession | None) -> dict[str, Any] | None:
    """Live shift data for the operator's machine."""
    if session is None:
        return None
    me = session.me
    tasks = {t.seq: t.description for t in session.context.tasks}
    current = me.task_seq if me else None
    remaining = session.task_order[session.task_order.index(current) + 1 :] if current else []
    fatigue = session.memory.get("last_fatigue")
    delta = session.memory.get("last_delta")
    return {
        "minute": session.minute,
        "clock": session.now.strftime("%H:%M") if session.now else None,
        "current_task": tasks.get(current) if current else "not started",
        "next_tasks": [tasks[s] for s in remaining],
        "minutes_vs_shadow": round(delta, 1) if delta is not None else None,
        "fatigue_score": fatigue.score if fatigue else None,
        "machine": (
            {
                "engine_on": me.engine_on,
                "seatbelt": me.seatbelt,
                "load_pct": round(me.load_pct),
                "fuel_lph": round(me.fuel_rate_lph, 1),
            }
            if me
            else None
        ),
        "recent_alerts": [a.message for a in session.memory.get("alerts", [])[-3:]],
    }


def nearby_hazards(session: ShiftSession | None) -> list[dict[str, Any]]:
    """Active hazard pins, nearest first, with distance from the operator's machine."""
    if session is None:
        return []
    me = session.me
    out = []
    for pin in session.memory.get("pins", []):
        dist = distance_m(me.lat, me.lon, pin.lat, pin.lon) if me else None
        out.append(
            {
                "kind": pin.kind,
                "description": pin.description,
                "distance_m": round(dist) if dist is not None else None,
                "confidence": pin.confidence,
            }
        )
    return sorted(out, key=lambda h: h["distance_m"] if h["distance_m"] is not None else 1e9)


def guide_search(index: GuideIndex, question: str) -> list[Hit]:
    return index.search(question, k=3)


# --- answer ----------------------------------------------------------------


def question_kind(question: str) -> str:
    """status: answered from live data. safety: guides only. general: anything else."""
    if STATUS_TERMS.search(question):
        return "status"
    if SAFETY_TERMS.search(question):
        return "safety"
    return "general"


def _fallback(kind: str, status: dict | None, hazards: list, hits: list[Hit]) -> ChatAnswer:
    if kind == "safety" and hits:
        top = hits[0]
        first = re.split(r"(?<=[.!?])\s", top.section.text.replace("\n", " "), maxsplit=2)
        return ChatAnswer(answer=" ".join(first[:2]).strip(), sources=[top.source])
    if kind == "status":
        if status is None:
            return ChatAnswer(answer=NO_SHIFT)
        parts = [f"Current task: {status['current_task']}."]
        delta = status["minutes_vs_shadow"]
        if delta is not None:
            side = "ahead of" if delta >= 0 else "behind"
            parts.append(f"You're {abs(delta):.0f} min {side} the shadow plan.")
        if status["next_tasks"]:
            parts.append(f"Next: {status['next_tasks'][0]}.")
        if hazards:
            h = hazards[0]
            parts.append(f"Nearest hazard: {h['description']} ({h['distance_m']} m).")
        return ChatAnswer(answer=" ".join(parts))
    if hits:
        return ChatAnswer(answer=hits[0].section.text.split("\n")[0], sources=[hits[0].source])
    return ChatAnswer(answer=ESCALATION, escalate_to_supervisor=True)


def answer(question: str, session: ShiftSession | None, index: GuideIndex) -> ChatAnswer:
    kind = question_kind(question)
    hits = guide_search(index, question)
    if kind == "safety" and not hits:
        return ChatAnswer(answer=ESCALATION, escalate_to_supervisor=True)

    status = shift_status(session)
    hazards = nearby_hazards(session)
    context = {
        "LIVE_SHIFT": status,
        "HAZARDS": hazards,
        "GUIDE_EXCERPTS": [{"source": h.source, "text": h.section.text} for h in hits],
    }
    user = f"{json.dumps(context)}\n\nOPERATOR_QUESTION: {question}"
    try:
        reply = get_llm().structured(SYSTEM_PROMPT, user, ChatAnswer)
    except LLMError:
        return _fallback(kind, status, hazards, hits)

    allowed = {h.source for h in hits}
    sources = [s for s in reply.sources if s in allowed]
    if reply.escalate_to_supervisor or (kind == "safety" and not sources):
        return ChatAnswer(answer=ESCALATION, escalate_to_supervisor=True)
    return reply.model_copy(update={"sources": sources})
