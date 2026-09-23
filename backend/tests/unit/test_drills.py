from collections import defaultdict

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.drills import SYSTEM_PROMPT, DrillContent, drills_for_shift, shift_moments
from app.db import LessonProgress, make_engine, make_session_factory
from app.main import create_app
from app.replay import demo_context, demo_frames
from app.runtime import ShiftRuntime
from data.generate import DEMO_SCRIPT, generate


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


def _replay(db, demo, predictor):
    runtime = ShiftRuntime(db, demo, predictor.predict(demo_context(demo)))
    by_minute = defaultdict(list)
    for f in demo_frames(demo):
        by_minute[f.minute].append(f)
    for minute in sorted(by_minute):
        runtime.process_minute(minute, by_minute[minute])


def test_drill_content_answer_must_point_at_an_option():
    with pytest.raises(ValidationError):
        DrillContent(scenario="s", question="q", options=["a", "b", "c"], answer=3, explanation="e")
    with pytest.raises(ValidationError):
        DrillContent(scenario="s", question="q", options=["a", "b"], answer=0, explanation="e")


def test_demo_shift_moments_in_time_order(demo, predictor, db_session):
    _replay(db_session, demo, predictor)
    moments = shift_moments(db_session, 1)
    assert [k for k, _, _ in moments] == [
        "seatbelt",
        "idle_deviation",
        "incident",
        "cycle_deviation",
        "fatigue",
    ]
    assert moments[2][1] == DEMO_SCRIPT["incident_minute"]


def test_template_drills_use_the_real_moment(demo, predictor, db_session):
    _replay(db_session, demo, predictor)
    drills = {d.kind: d for d in drills_for_shift(db_session, 1)}
    assert drills["seatbelt"].content.scenario.startswith("At 07:02")
    assert drills["incident"].content.scenario.startswith("At 10:20 you reported:")
    assert drills["idle_deviation"].practice == "grade"
    assert all(d.source == "template" for d in drills.values())
    assert drills_for_shift(db_session, 99) == []


def test_llm_drills_get_the_facts(demo, predictor, db_session, fake_llm):
    _replay(db_session, demo, predictor)
    llm_drill = DrillContent(
        scenario="At 07:02 you started up unbuckled.",
        question="What first?",
        options=["Buckle up", "Drive", "Wait"],
        answer=0,
        explanation="Buckle up first.",
    )
    fake_llm.on(DrillContent, llm_drill)
    drills = drills_for_shift(db_session, 1)
    assert all(d.source == "llm" for d in drills)
    drill_calls = [c for c in fake_llm.calls if c.get("schema") is DrillContent]
    assert drill_calls[0]["system"] == SYSTEM_PROMPT
    assert '"time": "07:02"' in drill_calls[0]["user"]


def test_drill_endpoints(demo, predictor):
    app = create_app(make_engine("sqlite://"))
    with TestClient(app) as client:
        db = make_session_factory(app.state.engine)()
        _replay(db, demo, predictor)
        drills = client.get("/shifts/1/drills").json()
        assert [d["kind"] for d in drills][:2] == ["seatbelt", "idle_deviation"]
        assert "answer" not in drills[0] and len(drills[0]["options"]) == 3

        right = client.post(
            "/shifts/1/drills/seatbelt-2/answer", json={"operator_id": 1, "answer": 1}
        ).json()
        assert right["correct"] is True
        assert right["correct_option"] == "Buckle up, then start the engine"
        wrong = client.post(
            "/shifts/1/drills/seatbelt-2/answer", json={"operator_id": 1, "answer": 0}
        ).json()
        assert wrong["correct"] is False
        scores = [
            r.quiz_score for r in db.query(LessonProgress).filter_by(lesson_id="drill:seatbelt")
        ]
        assert scores == [1.0, 0.0]
        db.close()

        missing = client.post("/shifts/1/drills/nope/answer", json={"operator_id": 1, "answer": 0})
        assert missing.status_code == 404
