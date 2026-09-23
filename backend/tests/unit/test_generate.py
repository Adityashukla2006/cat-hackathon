import json

import pytest

from app.geo import distance_m
from app.schemas import TelemetryFrame
from data.generate import DEMO_SCRIPT, SHIFT_MINUTES, generate


@pytest.fixture(scope="module")
def result():
    return generate(seed=42, n_shifts=60)


def _ex01(demo):
    return [f for f in demo["telemetry"] if f["machine_id"] == 1]


def _wl02(demo):
    return [f for f in demo["telemetry"] if f["machine_id"] == 2]


def test_same_seed_is_identical_and_other_seed_differs(result):
    again = generate(seed=42, n_shifts=60)
    assert result["history"].equals(again["history"])
    assert result["demo"] == again["demo"]
    assert not result["history"].equals(generate(seed=7, n_shifts=60)["history"])


def test_history_columns_and_ranges(result):
    history = result["history"]
    assert {"task_type", "experience_years", "ground", "duration_min", "idle_min", "fuel_l"} <= set(
        history.columns
    )
    assert history["shift_id"].nunique() == 60
    assert (history["duration_min"] > 0).all()
    assert (history["idle_min"] < history["duration_min"]).all()
    assert (history["fuel_l"] > 0).all()


def test_history_encodes_real_signal(result):
    history = result["history"]
    by_ground = history.groupby("ground")["duration_min"].mean()
    assert by_ground["muddy"] > by_ground["dry"]
    novices = history[history["experience_years"] < 3]["duration_min"].mean()
    veterans = history[history["experience_years"] > 8]["duration_min"].mean()
    assert novices > veterans


def test_demo_telemetry_is_complete_ordered_and_valid(result):
    demo = result["demo"]
    assert len(_ex01(demo)) == SHIFT_MINUTES
    assert len(_wl02(demo)) == SHIFT_MINUTES
    keys = [(f["minute"], f["machine_id"]) for f in demo["telemetry"]]
    assert keys == sorted(keys)
    for frame in demo["telemetry"][:50]:
        TelemetryFrame.model_validate(frame)


def test_demo_scripted_seatbelt_and_idle(result):
    ex01 = _ex01(result["demo"])
    lo, hi = DEMO_SCRIPT["seatbelt_unbuckled"]
    for f in ex01[lo : hi + 1]:
        assert f["engine_on"] and not f["seatbelt"]
    assert all(f["seatbelt"] for f in ex01 if f["minute"] > hi)
    assert not any(f["engine_on"] for f in ex01[: DEMO_SCRIPT["engine_on_minute"]])
    lo, hi = DEMO_SCRIPT["idle_window"]
    assert all(f["idle"] for f in ex01[lo : hi + 1])


def test_second_machine_reaches_incident_location_only_after_approach(result):
    demo = result["demo"]
    inc = demo["incident"]
    assert inc["minute"] == DEMO_SCRIPT["incident_minute"]
    for f in _wl02(demo):
        d = distance_m(f["lat"], f["lon"], inc["lat"], inc["lon"])
        if f["minute"] < DEMO_SCRIPT["second_machine_approach"][0]:
            assert d > 100
        if f["minute"] == DEMO_SCRIPT["second_machine_at_hazard"][0]:
            assert d < 30


def test_generate_writes_files(tmp_path):
    generate(seed=42, out_dir=tmp_path, n_shifts=5)
    assert (tmp_path / "history.csv").exists()
    demo = json.loads((tmp_path / "demo_shift.json").read_text())
    assert [t["seq"] for t in demo["tasks"]] == list(range(1, 9))
    roster = json.loads((tmp_path / "operators.json").read_text())
    assert "skill" not in roster[0]
