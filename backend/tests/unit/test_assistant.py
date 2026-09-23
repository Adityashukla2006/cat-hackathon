from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from app.agents.assistant import (
    ESCALATION,
    NO_SHIFT,
    SYSTEM_PROMPT,
    answer,
    nearby_hazards,
    question_kind,
    shift_status,
)
from app.db import make_engine
from app.guides import get_guides
from app.main import create_app
from app.replay import demo_context, demo_frames
from app.retrieval import GuideIndex, get_guide_index
from app.runtime import ShiftRuntime
from app.schemas import ChatAnswer
from data.generate import generate

SEATBELT_SOURCE = "Seatbelt and cab safety > Keep it on"


@pytest.fixture(scope="module")
def index():
    return GuideIndex([s for g in get_guides() for s in g.sections], llm=None)


@pytest.fixture
def live(predictor, db_session):
    """A demo shift replayed to minute 262: after the incident, the hazard pin, and the replan."""
    demo = generate(seed=42, n_shifts=2)["demo"]
    runtime = ShiftRuntime(db_session, demo, predictor.predict(demo_context(demo)))
    by_minute = defaultdict(list)
    for f in demo_frames(demo):
        by_minute[f.minute].append(f)
    for minute in range(263):
        runtime.process_minute(minute, by_minute[minute])
    return runtime.session


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("How far behind am I?", "status"),
        ("Where is the nearest hazard?", "status"),
        ("Can I unbuckle my seatbelt for a quick move?", "safety"),
        ("My track is sinking", "safety"),
        ("Hello there", "general"),
    ],
)
def test_question_kind(question, kind):
    assert question_kind(question) == kind


def test_shift_status_tool_reads_the_live_session(live):
    status = shift_status(live)
    assert status["minute"] == 262 and status["clock"] == "11:22"
    assert status["current_task"] == "Build stockpile from pit spoil"
    assert status["next_tasks"] == ["Grade the yard pad", "Load haul trucks at the pit"]
    assert status["minutes_vs_shadow"] < 0
    assert any("Idle" in a for a in status["recent_alerts"])
    assert shift_status(None) is None


def test_hazard_tool_lists_the_soft_ground_pin(live):
    (hazard,) = nearby_hazards(live)
    assert hazard["kind"] == "soft_ground" and hazard["distance_m"] > 100
    assert nearby_hazards(None) == []


def test_uncovered_safety_question_escalates_without_calling_llm(fake_llm, live):
    fatigue_only = GuideIndex(
        [s for g in get_guides() if g.id == "fatigue-and-breaks" for s in g.sections], llm=None
    )
    calls = len(fake_llm.calls)
    reply = answer("Is this hydraulic leak dangerous?", live, fatigue_only)
    assert reply == ChatAnswer(answer=ESCALATION, escalate_to_supervisor=True)
    assert len(fake_llm.calls) == calls


def test_llm_answer_gets_live_context_and_valid_sources(index, fake_llm, live):
    fake_llm.on(
        ChatAnswer,
        ChatAnswer(answer="Keep it fastened.", sources=[SEATBELT_SOURCE, "Made up > Source"]),
    )
    reply = answer("Can I unbuckle my seatbelt for a quick move?", live, index)
    assert reply.answer == "Keep it fastened."
    assert reply.sources == [SEATBELT_SOURCE]  # the invented source is dropped
    call = fake_llm.calls[-1]
    assert call["system"] == SYSTEM_PROMPT
    assert '"current_task": "Build stockpile from pit spoil"' in call["user"]
    assert '"kind": "soft_ground"' in call["user"]


def test_safety_answer_without_a_guide_source_is_escalated(index, fake_llm, live):
    fake_llm.on(ChatAnswer, ChatAnswer(answer="Sure, unbuckle.", sources=[]))
    reply = answer("Can I unbuckle my seatbelt for a quick move?", live, index)
    assert reply.escalate_to_supervisor and reply.answer == ESCALATION


def test_llm_choosing_to_escalate_is_respected(index, fake_llm, live):
    fake_llm.on(ChatAnswer, ChatAnswer(answer="?", escalate_to_supervisor=True))
    assert answer("Hello there", live, index).answer == ESCALATION


def test_fallback_answers_status_from_live_data(index, live):
    reply = answer("How far behind am I and what's next?", live, index)
    minutes = abs(round(live.memory["last_delta"]))
    assert f"{minutes} min behind the shadow plan" in reply.answer
    assert "Grade the yard pad" in reply.answer
    assert "Nearest hazard" in reply.answer


def test_fallback_answers_safety_from_the_guide(index):
    reply = answer("My track is sinking, what do I do?", None, index)
    (source,) = reply.sources
    assert source.startswith("Working on soft ground, slopes, and edges >")
    assert reply.answer and not reply.escalate_to_supervisor


def test_status_question_without_a_live_shift(index):
    assert answer("How far behind am I?", None, index).answer == NO_SHIFT


def test_chat_endpoint(index, fake_llm):
    fake_llm.on(ChatAnswer, ChatAnswer(answer="Keep it fastened.", sources=[SEATBELT_SOURCE]))
    app = create_app(make_engine("sqlite://"))
    app.dependency_overrides[get_guide_index] = lambda: index
    with TestClient(app) as client:
        question = "Can I unbuckle my seatbelt for a quick move?"
        body = client.post("/chat", json={"message": question}).json()
        assert body == {
            "answer": "Keep it fastened.",
            "sources": [SEATBELT_SOURCE],
            "escalate_to_supervisor": False,
        }
        assert client.post("/chat", json={"message": ""}).status_code == 422
