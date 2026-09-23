from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import training
from app.agents.coach import SYSTEM_PROMPT, CoachNote, advise, score_lessons
from app.db import Alert, Incident, Machine, Operator, Shift, make_engine, make_session_factory
from app.main import create_app


def _shift(db, operator_id=1) -> Shift:
    if db.get(Operator, operator_id) is None:
        db.add(Operator(id=operator_id, name="Op", experience_years=2))
    if db.get(Machine, 1) is None:
        db.add(Machine(id=1, name="EX-01", model="CAT 320", kind="excavator"))
    shift = Shift(
        operator_id=operator_id,
        machine_id=1,
        started_at=datetime(2026, 9, 23, 7, tzinfo=timezone.utc),
    )
    db.add(shift)
    db.commit()
    return shift


def _alert(db, shift, kind, minute=10):
    db.add(Alert(shift_id=shift.id, minute=minute, kind=kind, severity="warning", message=kind))
    db.commit()


def test_clean_record_has_no_recommendations(db_session):
    _shift(db_session)
    advice = advise(db_session, 1)
    assert advice.recommendations == [] and advice.suggest_instructor is None
    assert "Clean shift" in advice.note


def test_behaviour_maps_to_matching_lessons(db_session):
    shift = _shift(db_session)
    _alert(db_session, shift, "seatbelt")
    _alert(db_session, shift, "idle_deviation")
    db_session.add(
        Incident(
            shift_id=shift.id,
            minute=200,
            transcript="soft",
            report={"category": "ground", "summary": "Track sank at the ramp."},
        )
    )
    db_session.commit()
    recs = score_lessons(db_session, 1)
    assert [r.lesson_id for r in recs] == ["seatbelt", "soft-ground", "idle-fuel"]
    assert recs[1].reasons == ["reported: Track sank at the ramp."]
    assert recs[2].practice == "grade"


def test_passing_a_lesson_lowers_its_priority(db_session):
    shift = _shift(db_session)
    _alert(db_session, shift, "seatbelt")
    _alert(db_session, shift, "fatigue")
    assert score_lessons(db_session, 1)[0].lesson_id == "seatbelt"
    training.record_result(db_session, 1, "seatbelt", 1.0)
    recs = score_lessons(db_session, 1)
    assert [r.lesson_id for r in recs] == ["fatigue", "seatbelt"]
    assert recs[1].weight == 1.5


def test_low_practice_scores_count(db_session):
    _shift(db_session)
    training.record_result(db_session, 1, "sim:dig", 0.3)
    training.record_result(db_session, 1, "walkaround:leak", 0.9)
    recs = score_lessons(db_session, 1)
    assert [r.lesson_id for r in recs] == ["joystick"]
    assert recs[0].reasons == ["low score on sim dig practice"]


def test_other_operators_behaviour_is_ignored(db_session):
    other = _shift(db_session, operator_id=2)
    _alert(db_session, other, "seatbelt")
    _shift(db_session, operator_id=1)
    assert score_lessons(db_session, 1) == []


def test_instructor_suggested_for_heavy_unpassed_topic(db_session, fake_llm):
    shift = _shift(db_session)
    _alert(db_session, shift, "seatbelt")
    fake_llm.on(CoachNote, CoachNote(note="Start with the seatbelt lesson."))
    advice = advise(db_session, 1)
    assert advice.suggest_instructor == "seatbelt"
    assert advice.note == "Start with the seatbelt lesson."
    assert fake_llm.calls[-1]["system"] == SYSTEM_PROMPT
    training.record_result(db_session, 1, "seatbelt", 1.0)
    assert advise(db_session, 1).suggest_instructor is None


def test_template_note_without_llm(db_session):
    shift = _shift(db_session)
    _alert(db_session, shift, "fatigue")
    assert advise(db_session, 1).note == (
        "Start with fatigue and breaks: fatigue built up late in the shift."
    )


def test_coach_endpoint():
    app = create_app(make_engine("sqlite://"))
    with TestClient(app) as client:
        db = make_session_factory(app.state.engine)()
        shift = _shift(db)
        _alert(db, shift, "seatbelt")
        db.close()
        body = client.get("/operators/1/coach").json()
        assert body["recommendations"][0]["lesson_id"] == "seatbelt"
        assert client.get("/operators/42/coach").status_code == 404


@pytest.mark.parametrize("kind", ["seatbelt", "idle_deviation", "cycle_deviation", "fatigue"])
def test_every_weighted_alert_points_at_a_real_lesson(kind):
    from app.agents.coach import ALERT_WEIGHTS

    assert ALERT_WEIGHTS[kind][0] in training.LESSONS
