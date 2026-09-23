import pytest
from fastapi.testclient import TestClient

from app.db import make_engine
from app.main import create_app
from app.schemas import ShiftContext
from app.shadow.predictor import (
    ModelsNotTrainedError,
    ShadowPredictor,
    get_predictor,
    schedule_delta,
)


def _ctx(**overrides) -> ShiftContext:
    data = {
        "shift_id": 1,
        "operator_id": 1,
        "experience_years": 2.5,
        "machine_kind": "excavator",
        "ground": "wet",
        "weather": {"temp_c": 14.0, "rain_mm": 4.0, "wind_kph": 18.0},
        "tasks": [
            {"seq": 2, "task_type": "load_truck", "description": "Load trucks"},
            {"seq": 1, "task_type": "dig", "description": "Dig pit face A"},
            {"seq": 3, "task_type": "trench", "description": "Cut ditch"},
        ],
    }
    data.update(overrides)
    return ShiftContext.model_validate(data)


def test_timeline_is_sequential_with_valid_bands(predictor):
    timeline = predictor.predict(_ctx())
    assert [t.seq for t in timeline.tasks] == [1, 2, 3]
    assert timeline.tasks[0].start_min == 0
    for prev, nxt in zip(timeline.tasks, timeline.tasks[1:]):
        assert nxt.start_min == pytest.approx(prev.start_min + prev.duration_min.p50, abs=0.01)
    for t in timeline.tasks:
        assert 0 <= t.duration_min.p10 <= t.duration_min.p50 <= t.duration_min.p90
        assert 0 <= t.expected_idle_min <= t.duration_min.p50
        assert t.expected_fuel_l > 0
    assert timeline.total_min.p50 == pytest.approx(sum(t.duration_min.p50 for t in timeline.tasks))


def test_conditions_move_predictions_the_right_way(predictor):
    dry = predictor.predict(_ctx(ground="dry", weather={"temp_c": 20, "rain_mm": 0, "wind_kph": 5}))
    muddy = predictor.predict(
        _ctx(ground="muddy", weather={"temp_c": 20, "rain_mm": 8, "wind_kph": 5})
    )
    assert muddy.total_min.p50 > dry.total_min.p50
    veteran = predictor.predict(_ctx(operator_id=5, experience_years=14.0))
    novice = predictor.predict(_ctx(operator_id=4, experience_years=1.0))
    assert novice.total_min.p50 > veteran.total_min.p50


def test_prediction_is_deterministic(predictor):
    assert predictor.predict(_ctx()) == predictor.predict(_ctx())


def test_schedule_delta(predictor):
    timeline = predictor.predict(_ctx())
    task2 = timeline.tasks[1]
    # started task 2 exactly on time and working at shadow pace -> zero delta
    on_time = schedule_delta(timeline, task2.start_min + 5, 2, task2.start_min)
    assert on_time == pytest.approx(0, abs=0.01)
    # started task 2 ten minutes late -> ten minutes behind
    late = schedule_delta(timeline, task2.start_min + 15, 2, task2.start_min + 10)
    assert late == pytest.approx(-10, abs=0.01)
    # overrunning past p50 keeps falling behind
    overrun = schedule_delta(
        timeline, task2.start_min + task2.duration_min.p50 + 7, 2, task2.start_min
    )
    assert overrun == pytest.approx(-7, abs=0.01)
    with pytest.raises(ValueError):
        schedule_delta(timeline, 0, 99, 0)


def test_load_raises_when_models_missing(tmp_path):
    with pytest.raises(ModelsNotTrainedError, match="ml/train.py"):
        ShadowPredictor.load(tmp_path)


def test_predict_endpoint(predictor):
    app = create_app(make_engine("sqlite://"))
    app.dependency_overrides[get_predictor] = lambda: predictor
    with TestClient(app) as client:
        response = client.post("/shadow/predict", json=_ctx().model_dump())
    assert response.status_code == 200
    body = response.json()
    assert len(body["tasks"]) == 3
    assert body["total_min"]["p10"] <= body["total_min"]["p50"] <= body["total_min"]["p90"]


def test_predict_endpoint_503_without_models(tmp_path):
    def missing() -> ShadowPredictor:
        return ShadowPredictor.load(tmp_path)

    app = create_app(make_engine("sqlite://"))
    app.dependency_overrides[get_predictor] = missing
    with TestClient(app) as client:
        response = client.post("/shadow/predict", json=_ctx().model_dump())
    assert response.status_code == 503
