from types import SimpleNamespace

import openai
import pytest
from fastapi.testclient import TestClient

from app.agents.planner import (
    SYSTEM_PROMPT,
    plan_shift,
    planner_node,
    score_task_risk,
    score_timeline,
)
from app.agents.state import ShiftSession
from app.db import make_engine
from app.graph import build_graph, run_event
from app.llm import LLMError, OpenAILLM
from app.main import create_app
from app.replay import demo_context, get_demo
from app.schemas import Briefing, PlannedTask, QuantileRange, ShadowTask, ShiftContext
from app.shadow.predictor import get_predictor
from data.generate import generate

LLM_BRIEFING = Briefing(
    headline="Soft ground on the ramp today",
    key_risks=["Ramp ditch near the edge"],
    focus_tip="Keep tracks square to the edge.",
)


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


@pytest.fixture
def ctx(demo) -> ShiftContext:
    return demo_context(demo)


def _task(task_type="dig", p50=50.0, p90=55.0, start=0.0) -> ShadowTask:
    return ShadowTask(
        seq=1,
        task_type=task_type,
        description="x",
        duration_min=QuantileRange(p10=p50 - 5, p50=p50, p90=p90),
        start_min=start,
        expected_idle_min=3,
        expected_fuel_l=10,
    )


def _ctx(**overrides) -> ShiftContext:
    data = {
        "shift_id": 1,
        "operator_id": 5,
        "experience_years": 14,
        "machine_kind": "excavator",
        "ground": "dry",
        "weather": {"temp_c": 20, "rain_mm": 0, "wind_kph": 5},
        "tasks": [{"seq": 1, "task_type": "dig", "description": "x"}],
    }
    data.update(overrides)
    return ShiftContext.model_validate(data)


def test_calm_day_veteran_has_low_risk_with_no_reasons():
    risk = score_task_risk(_task(), PlannedTask(seq=1, task_type="dig", description="x"), _ctx())
    assert risk.score == pytest.approx(0.2 + (5 / 50) / 0.6 * 0.2, abs=0.01)
    assert risk.reasons == []


def test_each_risk_factor_adds_score_and_a_reason():
    planned = PlannedTask(seq=1, task_type="trench", description="x", zone="ramp")
    ctx = _ctx(ground="muddy", experience_years=1)
    calm = score_task_risk(_task("trench"), planned.model_copy(update={"zone": "pit"}), _ctx())
    risky = score_task_risk(_task("trench", p90=90, start=400), planned, ctx, ["ramp"])
    assert risky.score > calm.score + 0.6
    joined = " ".join(risky.reasons)
    for word in ("run long", "muddy", "edge", "hazard", "3 years", "late"):
        assert word in joined
    assert risky.score <= 1.0


def test_score_timeline_fills_scores_and_sorts_by_risk(ctx, predictor):
    scored, risks = score_timeline(ctx, predictor.predict(ctx))
    assert all(t.risk_score is not None for t in scored.tasks)
    assert [r.score for r in risks] == sorted((r.score for r in risks), reverse=True)
    # the demo's ramp ditch (edge zone, wet ground) is the riskiest task
    assert risks[0].seq == 3


def test_plan_uses_llm_briefing_with_scored_facts(ctx, predictor, fake_llm):
    fake_llm.on(Briefing, LLM_BRIEFING)
    result = plan_shift(ctx, predictor.predict(ctx))
    assert result.briefing == LLM_BRIEFING
    assert result.briefing_source == "llm"
    call = fake_llm.calls[0]
    assert call["system"] == SYSTEM_PROMPT
    assert '"ground": "wet"' in call["user"] and '"seq": 3' in call["user"]


def test_plan_falls_back_to_template_when_llm_fails(ctx, predictor, fake_llm):
    result = plan_shift(ctx, predictor.predict(ctx))  # no response registered -> LLMError
    assert result.briefing_source == "template"
    assert "task 3" in result.briefing.headline
    assert "soft" in result.briefing.focus_tip.lower()
    assert len(result.briefing.key_risks) == 3


def test_openai_sdk_errors_become_llm_errors():
    def boom(**_):
        raise openai.APIConnectionError(request=SimpleNamespace(method="POST", url="x"))

    client = SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=boom)))
    )
    with pytest.raises(LLMError, match="APIConnectionError"):
        OpenAILLM(model="m", client=client).structured("s", "u", Briefing)


def test_planner_node_updates_session_via_graph(ctx, predictor, fake_llm):
    fake_llm.on(Briefing, LLM_BRIEFING)
    session = ShiftSession(shift_id=1, machine_id=1, context=ctx, timeline=predictor.predict(ctx))
    state = run_event(build_graph(planner=planner_node), session, {"kind": "plan"})
    assert state["briefing"] == LLM_BRIEFING
    assert session.timeline.tasks[0].risk_score is not None
    assert session.memory["risks"][0].seq == 3


def test_planner_node_requires_timeline(ctx):
    with pytest.raises(ValueError):
        planner_node({"session": ShiftSession(shift_id=1, machine_id=1, context=ctx)})


def test_demo_plan_endpoint_is_computed_once(demo, predictor, fake_llm):
    fake_llm.on(Briefing, LLM_BRIEFING)
    app = create_app(make_engine("sqlite://"))
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_predictor] = lambda: predictor
    with TestClient(app) as client:
        first = client.get("/demo/plan").json()
        second = client.get("/demo/plan").json()
    assert first == second
    assert first["briefing"]["headline"] == LLM_BRIEFING.headline
    assert len(fake_llm.calls) == 1
