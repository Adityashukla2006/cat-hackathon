import json

import lightgbm as lgb
import numpy as np
import pytest

from app.shadow.features import calibrated_band, to_frame
from data.generate import generate
from ml.train import backtest, conformal_margin, run, split_by_shift, train_models


@pytest.fixture(scope="module")
def history():
    return generate(seed=42, n_shifts=150)["history"]


@pytest.fixture(scope="module")
def trained(history):
    train, test = split_by_shift(history)
    return train, test, train_models(train, seed=42)


def test_split_by_shift_is_time_ordered_and_disjoint(history):
    train, test = split_by_shift(history)
    assert train["shift_id"].max() < test["shift_id"].min()
    assert len(train) + len(test) == len(history)


def test_backtest_beats_baseline_and_band_is_calibrated(trained):
    train, test, models = trained
    metrics = backtest(models, test, train)["duration"]
    assert metrics["mae_p50"] < 0.7 * metrics["mae_baseline_median"]
    assert 0.65 <= metrics["coverage_p10_p90"] <= 0.95
    assert metrics["pinball"]["p50"] > 0


def test_training_is_deterministic(history, trained):
    train, test, models = trained
    again = train_models(train, seed=42)
    x = to_frame(test)
    for name, booster in models.boosters.items():
        np.testing.assert_array_equal(booster.predict(x), again.boosters[name].predict(x))
    assert again.band_margin == models.band_margin


def test_conformal_margin_hits_target_coverage():
    rng = np.random.default_rng(42)
    y = rng.normal(0, 1, 1000)
    p10, p90 = np.full(1000, -0.5), np.full(1000, 0.5)
    margin = conformal_margin(y, p10, p90, 0.8)
    covered = np.mean((y >= p10 - margin) & (y <= p90 + margin))
    assert 0.79 <= covered <= 0.82


def test_calibrated_band_orders_and_clips():
    p10, p50, p90 = calibrated_band(np.array([5.0]), np.array([4.0]), np.array([3.0]), 1.0)
    assert p10[0] == 3.0 and p50[0] == 4.0 and p90[0] == 5.0
    p10, _, _ = calibrated_band(np.array([0.5]), np.array([1.0]), np.array([2.0]), 3.0)
    assert p10[0] == 0.0


def test_run_writes_loadable_models(tmp_path):
    data_dir = tmp_path / "data"
    generate(seed=42, out_dir=data_dir, n_shifts=80)
    metrics = run(data_dir / "history.csv", tmp_path / "models", seed=42)
    saved = json.loads((tmp_path / "models" / "metrics.json").read_text())
    assert saved == metrics
    assert json.loads((tmp_path / "models" / "calibration.json").read_text())["coverage"] == 0.8
    booster = lgb.Booster(model_file=str(tmp_path / "models" / "duration_p50.txt"))
    assert booster.num_trees() > 0
