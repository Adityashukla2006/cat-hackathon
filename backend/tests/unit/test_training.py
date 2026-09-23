import pytest
from fastapi.testclient import TestClient

from app import training
from app.db import Operator, make_engine, make_session_factory
from app.guides import get_guides
from app.main import create_app


@pytest.fixture
def client():
    app = create_app(make_engine("sqlite://"))
    with TestClient(app) as c:
        db = make_session_factory(app.state.engine)()
        if db.get(Operator, 1) is None:
            db.add(Operator(id=1, name="Sam Rivera", experience_years=2.5))
            db.commit()
        db.close()
        yield c


def test_curriculum_lessons_point_at_real_guides_and_valid_answers():
    guide_ids = {g.id for g in get_guides()}
    assert len(training.LESSONS) == 8
    for lesson in training.LESSONS.values():
        assert lesson.guide_id in guide_ids
        assert len(lesson.quiz) == 3
        for q in lesson.quiz:
            assert 0 <= q.answer < len(q.options)
        assert lesson.practice in (None, "walkaround", "reach", "dig", "grade")


def test_grade_scores_and_passes():
    lesson = training.LESSONS["seatbelt"]
    perfect = [q.answer for q in lesson.quiz]
    result = training.grade(lesson, perfect)
    assert result.score == 1.0 and result.passed and all(result.correct)
    one_wrong = training.grade(lesson, [(perfect[0] + 1) % 3, *perfect[1:]])
    assert one_wrong.score == 0.67 and one_wrong.passed
    two_wrong = training.grade(lesson, [(a + 1) % 3 for a in perfect[:2]] + perfect[2:])
    assert not two_wrong.passed
    with pytest.raises(ValueError):
        training.grade(lesson, [0])


def test_best_scores_keep_the_highest(db_session):
    db_session.add(Operator(id=1, name="x", experience_years=1))
    db_session.commit()
    training.record_result(db_session, 1, "seatbelt", 0.33)
    training.record_result(db_session, 1, "seatbelt", 1.0)
    training.record_result(db_session, 1, "sim:dig", 0.4)
    assert training.best_scores(db_session, 1) == {"seatbelt": 1.0, "sim:dig": 0.4}


def test_lesson_endpoint_hides_answers(client):
    body = client.get("/training/lessons/soft-ground").json()
    assert body["guide_id"] == "soft-ground-and-edges"
    assert len(body["questions"]) == 3
    assert "answer" not in body["questions"][0] and "explanation" not in body["questions"][0]
    assert client.get("/training/lessons/nope").status_code == 404


def test_quiz_submission_records_progress(client):
    answers = [q.answer for q in training.LESSONS["seatbelt"].quiz]
    result = client.post(
        "/training/lessons/seatbelt/quiz", json={"operator_id": 1, "answers": answers}
    ).json()
    assert result["passed"] and result["score"] == 1.0
    modules = client.get("/training/modules", params={"operator_id": 1}).json()
    seatbelt = next(ls for m in modules for ls in m["lessons"] if ls["id"] == "seatbelt")
    assert seatbelt == {
        "id": "seatbelt",
        "title": "Seatbelt and cab safety",
        "guide_id": "seatbelt-and-cab-safety",
        "practice": None,
        "best_score": 1.0,
        "passed": True,
    }
    bad = client.post("/training/lessons/seatbelt/quiz", json={"operator_id": 1, "answers": [0]})
    assert bad.status_code == 422
    stranger = client.post(
        "/training/lessons/seatbelt/quiz", json={"operator_id": 99, "answers": answers}
    )
    assert stranger.status_code == 404


def test_practice_results_endpoint(client):
    ok = client.post(
        "/training/results", json={"operator_id": 1, "activity_id": "sim:dig", "score": 0.8}
    )
    assert ok.status_code == 201
    bad = client.post(
        "/training/results", json={"operator_id": 1, "activity_id": "hack", "score": 0.8}
    )
    assert bad.status_code == 422


def test_guide_endpoint(client):
    body = client.get("/guides/fatigue-and-breaks").json()
    assert body["title"] == "Fatigue and breaks"
    assert [s["heading"] for s in body["sections"]][:2] == [
        "Overview",
        "Signs you are getting tired",
    ]
    assert client.get("/guides/nope").status_code == 404
