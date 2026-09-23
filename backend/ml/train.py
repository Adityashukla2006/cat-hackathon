"""Train the shadow models: LightGBM quantile models for task time plus idle and fuel regressors.

Usage: python ml/train.py [--data data/generated/history.csv] [--out ml/models] [--seed 42]

The p10-p90 band is conformally calibrated (CQR) on the most recent 20% of the fitting shifts,
so it covers roughly 80% of actual task times. The last 20% of all shifts is held out as a
backtest and the results are written to metrics.json next to the models.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.shadow.features import (  # noqa: E402
    QUANTILES,
    TARGET_DURATION,
    TARGET_FUEL,
    TARGET_IDLE,
    calibrated_band,
    to_frame,
)

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_DATA = BACKEND / "data" / "generated" / "history.csv"
DEFAULT_OUT = BACKEND / "ml" / "models"
NUM_ROUNDS = 200
TARGET_COVERAGE = 0.8


@dataclass
class ShadowModels:
    boosters: dict[str, lgb.Booster]
    band_margin: float  # minutes added to each side of the p10-p90 band


def _params(seed: int, **overrides: Any) -> dict[str, Any]:
    params = {
        "learning_rate": 0.05,
        "num_leaves": 7,
        "min_data_in_leaf": 40,
        "feature_fraction": 0.9,
        "seed": seed,
        "deterministic": True,
        "force_col_wise": True,
        "num_threads": 1,
        "verbose": -1,
    }
    params.update(overrides)
    return params


def split_by_shift(df: pd.DataFrame, test_frac: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Time-ordered split: the most recent shifts go to the second frame."""
    shifts = np.sort(df["shift_id"].unique())
    cutoff = shifts[int(len(shifts) * (1 - test_frac))]
    return df[df["shift_id"] < cutoff], df[df["shift_id"] >= cutoff]


def _fit(df: pd.DataFrame, seed: int) -> dict[str, lgb.Booster]:
    x = to_frame(df)
    boosters: dict[str, lgb.Booster] = {}
    for name, alpha in QUANTILES.items():
        boosters[f"duration_{name}"] = lgb.train(
            _params(seed, objective="quantile", alpha=alpha),
            lgb.Dataset(x, df[TARGET_DURATION]),
            NUM_ROUNDS,
        )
    for name, target in (("idle", TARGET_IDLE), ("fuel", TARGET_FUEL)):
        boosters[name] = lgb.train(
            _params(seed, objective="regression"), lgb.Dataset(x, df[target]), NUM_ROUNDS
        )
    return boosters


def _raw_quantiles(boosters: dict[str, lgb.Booster], df: pd.DataFrame) -> dict[str, np.ndarray]:
    x = to_frame(df)
    return {name: boosters[f"duration_{name}"].predict(x) for name in QUANTILES}


def conformal_margin(y: np.ndarray, p10: np.ndarray, p90: np.ndarray, coverage: float) -> float:
    """Split-conformal CQR margin: the finite-sample quantile of the nonconformity scores."""
    scores = np.maximum(p10 - y, y - p90)
    n = len(scores)
    level = min(1.0, math.ceil((n + 1) * coverage) / n)
    return float(np.quantile(scores, level, method="higher"))


def train_models(df: pd.DataFrame, seed: int = 42) -> ShadowModels:
    fit, cal = split_by_shift(df)
    boosters = _fit(fit, seed)
    q = _raw_quantiles(boosters, cal)
    p10, _, p90 = calibrated_band(q["p10"], q["p50"], q["p90"], 0.0)
    margin = conformal_margin(cal[TARGET_DURATION].to_numpy(), p10, p90, TARGET_COVERAGE)
    return ShadowModels(boosters, margin)


def pinball_loss(y: np.ndarray, pred: np.ndarray, alpha: float) -> float:
    diff = y - pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def backtest(models: ShadowModels, test: pd.DataFrame, train: pd.DataFrame) -> dict:
    x = to_frame(test)
    y = test[TARGET_DURATION].to_numpy()
    q = _raw_quantiles(models.boosters, test)
    p10, p50, p90 = calibrated_band(q["p10"], q["p50"], q["p90"], models.band_margin)
    baseline = np.full_like(y, float(train[TARGET_DURATION].median()))
    return {
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "duration": {
            "pinball": {n: pinball_loss(y, q[n], a) for n, a in QUANTILES.items()},
            "band_margin_min": models.band_margin,
            "coverage_p10_p90": float(np.mean((y >= p10) & (y <= p90))),
            "mae_p50": float(np.mean(np.abs(y - p50))),
            "mae_baseline_median": float(np.mean(np.abs(y - baseline))),
        },
        "idle_mae": float(np.mean(np.abs(test[TARGET_IDLE] - models.boosters["idle"].predict(x)))),
        "fuel_mae": float(np.mean(np.abs(test[TARGET_FUEL] - models.boosters["fuel"].predict(x)))),
    }


def save_models(models: ShadowModels, metrics: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, booster in models.boosters.items():
        booster.save_model(str(out_dir / f"{name}.txt"))
    (out_dir / "calibration.json").write_text(
        json.dumps({"band_margin_min": models.band_margin, "coverage": TARGET_COVERAGE})
    )
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))


def run(data: Path, out_dir: Path, seed: int = 42) -> dict:
    history = pd.read_csv(data)
    train, test = split_by_shift(history)
    metrics = backtest(train_models(train, seed), test, train)
    # ship models refit on all history; the backtest numbers come from the held-out fit
    save_models(train_models(history, seed), metrics, out_dir)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    metrics = run(args.data, args.out, args.seed)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
