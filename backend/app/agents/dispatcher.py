"""Dispatcher: risk-aware reordering of the remaining tasks, with a one-line explanation.

The order is decided in Python: tasks in a zone with an active hazard go last, then riskier
tasks come first so they're done while the operator is fresher. The LLM only phrases the
one-line explanation, with a template fallback.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.agents.planner import score_timeline
from app.agents.sentinel import get_state
from app.agents.state import GraphState, ShiftSession
from app.llm import LLMError, get_llm
from app.schemas import Replan
from app.shadow.predictor import reorder_timeline

SYSTEM_PROMPT = """You tell a heavy-equipment operator why their remaining tasks were reordered.
Write ONE sentence of at most 20 words, plain words, no jargon.
Use only the facts provided: the reason for the replan, the old and new order, and why each
task moved. Do not invent hazards or instructions."""


class DispatchNote(BaseModel):
    explanation: str = Field(max_length=200)


class DispatchPlan(BaseModel):
    done_or_active: list[int]
    old_remaining: list[int]
    new_remaining: list[int]
    deferred: list[int]
    risk: dict[int, float]
    descriptions: dict[int, str]

    @property
    def new_order(self) -> list[int]:
        return self.done_or_active + self.new_remaining

    @property
    def changed(self) -> bool:
        return self.new_remaining != self.old_remaining


def plan_order(session: ShiftSession) -> DispatchPlan:
    if session.timeline is None:
        raise ValueError("dispatcher needs the shadow timeline")
    # score once against the planned timeline and reuse it: re-scoring after a reorder would
    # shift start times, change the late-shift factor, and make consecutive replans flip-flop
    if "risks" not in session.memory:
        session.memory["risks"] = score_timeline(session.context, session.timeline)[1]
    risk = {r.seq: r.score for r in session.memory["risks"]}
    zones = {t.seq: t.zone for t in session.context.tasks}
    hazards = set(session.memory.get("hazard_zones", ()))

    current = session.me.task_seq if session.me else None
    order = session.task_order
    cut = order.index(current) + 1 if current in order else 0
    done_or_active, remaining = order[:cut], order[cut:]

    deferred = [seq for seq in remaining if zones.get(seq) in hazards]
    new_remaining = sorted(
        remaining, key=lambda seq: (seq in deferred, -risk[seq], remaining.index(seq))
    )
    return DispatchPlan(
        done_or_active=done_or_active,
        old_remaining=remaining,
        new_remaining=new_remaining,
        deferred=deferred,
        risk=risk,
        descriptions={t.seq: t.description for t in session.context.tasks},
    )


def template_explanation(plan: DispatchPlan, reason: str | None) -> str:
    first = plan.descriptions[plan.new_remaining[0]].lower()
    text = f"Next up: {first}, the riskiest remaining task, while you're fresh."
    if plan.deferred:
        text = f"Moved hazard-zone work last. {text}"
    return text[:200]


def explain(plan: DispatchPlan, reason: str | None) -> str:
    facts: dict[str, Any] = {
        "reason_for_replan": reason,
        "old_order": [plan.descriptions[s] for s in plan.old_remaining],
        "new_order": [plan.descriptions[s] for s in plan.new_remaining],
        "deferred_for_hazard": [plan.descriptions[s] for s in plan.deferred],
        "risk_by_task": {plan.descriptions[s]: plan.risk[s] for s in plan.new_remaining},
    }
    try:
        note = get_llm().structured(SYSTEM_PROMPT, json.dumps(facts), DispatchNote)
        return note.explanation
    except LLMError:
        return template_explanation(plan, reason)


def dispatcher_node(state: GraphState) -> dict[str, Any]:
    session = state["session"]
    plan = plan_order(session)
    if not plan.changed:
        return {"replan": None}  # the current order already fits; don't interrupt the operator
    session.task_order = plan.new_order
    session.timeline = reorder_timeline(session.timeline, plan.new_order)
    tracker = get_state(session).tracker
    if tracker is not None:
        tracker.timeline = session.timeline
    replan = Replan(new_order=plan.new_order, explanation=explain(plan, state.get("replan_reason")))
    session.memory.setdefault("replans", []).append((session.minute, replan))
    return {"replan": replan}
