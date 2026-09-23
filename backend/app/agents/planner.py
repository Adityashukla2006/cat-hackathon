"""Planner: scores each shadow task's risk and writes the pre-shift briefing.

Risk scoring is deterministic. The LLM only turns the scored facts into a short briefing, and a
template briefing is used whenever the LLM is unavailable.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from app.agents.state import GraphState
from app.llm import LLMError, get_llm
from app.schemas import Briefing, PlannedTask, ShadowTask, ShadowTimeline, ShiftContext

TASK_BASE_RISK = {"dig": 0.2, "load_truck": 0.15, "trench": 0.35, "grade": 0.2, "stockpile": 0.2}
GROUND_RISK = {"dry": 0.0, "wet": 0.1, "muddy": 0.2}
EDGE_ZONES = {"ramp", "trench"}
NOVICE_YEARS = 3.0
LATE_SHIFT_HOUR = 13.0
HIGH_RISK = 0.6

SYSTEM_PROMPT = """You write the pre-shift briefing for a heavy-equipment operator.
Use only the facts provided. Do not invent hazards, numbers, or procedures.
headline: one short sentence naming the highest-risk task (tasks_by_risk[0]) and its main reason.
key_risks: at most 3 short items, most important first, each naming a task and its reasons.
focus_tip: one practical sentence the operator can act on.
Plain words, no jargon, the operator reads this on a tablet wearing gloves."""


class TaskRisk(BaseModel):
    seq: int
    description: str
    score: float
    reasons: list[str]


class PlanResult(BaseModel):
    timeline: ShadowTimeline
    risks: list[TaskRisk]
    briefing: Briefing
    briefing_source: str  # "llm" or "template"


def score_task_risk(
    task: ShadowTask,
    planned: PlannedTask,
    ctx: ShiftContext,
    hazard_zones: Iterable[str] = (),
) -> TaskRisk:
    reasons: list[str] = []
    score = TASK_BASE_RISK[task.task_type]

    spread = (task.duration_min.p90 - task.duration_min.p50) / max(task.duration_min.p50, 1.0)
    score += min(spread / 0.6, 1.0) * 0.2
    if spread > 0.3:
        reasons.append(f"could run long, up to {task.duration_min.p90:.0f} min")

    if GROUND_RISK[ctx.ground]:
        score += GROUND_RISK[ctx.ground]
        reasons.append(f"{ctx.ground} ground")
    if planned.zone in EDGE_ZONES:
        score += 0.15
        reasons.append(f"works near the {planned.zone} edge")
    if planned.zone and planned.zone in set(hazard_zones):
        score += 0.25
        reasons.append(f"active hazard reported at the {planned.zone}")
    if ctx.experience_years < NOVICE_YEARS:
        score += 0.1
        reasons.append("less than 3 years on this machine")
    if ctx.start_hour + task.start_min / 60.0 >= LATE_SHIFT_HOUR:
        score += 0.05
        reasons.append("late in the shift")

    return TaskRisk(
        seq=task.seq,
        description=task.description,
        score=round(min(score, 1.0), 2),
        reasons=reasons,
    )


def score_timeline(
    ctx: ShiftContext, timeline: ShadowTimeline, hazard_zones: Iterable[str] = ()
) -> tuple[ShadowTimeline, list[TaskRisk]]:
    planned = {t.seq: t for t in ctx.tasks}
    zones = list(hazard_zones)
    risks = [score_task_risk(t, planned[t.seq], ctx, zones) for t in timeline.tasks]
    by_seq = {r.seq: r.score for r in risks}
    scored = timeline.model_copy(
        update={
            "tasks": [t.model_copy(update={"risk_score": by_seq[t.seq]}) for t in timeline.tasks]
        }
    )
    return scored, sorted(risks, key=lambda r: (-r.score, r.seq))


def template_briefing(ctx: ShiftContext, risks: list[TaskRisk]) -> Briefing:
    top = risks[0]
    headline = f"Highest risk today: task {top.seq}, {top.description.lower()}."
    key_risks = [f"Task {r.seq}: {', '.join(r.reasons) or 'routine'}" for r in risks[:3]]
    if ctx.ground != "dry":
        tip = "Ground is soft after rain. Go slow near edges and stop if a track starts to sink."
    else:
        tip = "Keep the bucket low when travelling and check your swing area before every swing."
    return Briefing(headline=headline, key_risks=key_risks, focus_tip=tip)


def _facts(ctx: ShiftContext, timeline: ShadowTimeline, risks: list[TaskRisk]) -> str:
    facts: dict[str, Any] = {
        "operator_experience_years": ctx.experience_years,
        "machine": ctx.machine_kind,
        "ground": ctx.ground,
        "weather": ctx.weather.model_dump(),
        "expected_shift_minutes": round(timeline.total_min.p50),
        "tasks_by_risk": [r.model_dump() for r in risks],
        "risk_points": timeline.risk_points,
    }
    return json.dumps(facts)


def write_briefing(
    ctx: ShiftContext, timeline: ShadowTimeline, risks: list[TaskRisk]
) -> tuple[Briefing, str]:
    try:
        briefing = get_llm().structured(SYSTEM_PROMPT, _facts(ctx, timeline, risks), Briefing)
        return briefing, "llm"
    except LLMError:
        return template_briefing(ctx, risks), "template"


def plan_shift(
    ctx: ShiftContext, timeline: ShadowTimeline, hazard_zones: Iterable[str] = ()
) -> PlanResult:
    scored, risks = score_timeline(ctx, timeline, hazard_zones)
    briefing, source = write_briefing(ctx, scored, risks)
    return PlanResult(timeline=scored, risks=risks, briefing=briefing, briefing_source=source)


def planner_node(state: GraphState) -> dict[str, Any]:
    session = state["session"]
    if session.timeline is None:
        raise ValueError("planner needs the shadow timeline before the shift starts")
    result = plan_shift(session.context, session.timeline, session.memory.get("hazard_zones", ()))
    session.timeline = result.timeline
    session.memory["risks"] = result.risks
    return {"briefing": result.briefing}
