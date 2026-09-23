"""Feature spec shared by model training (ml/train.py) and the shadow prediction service."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd

TASK_TYPES = ["dig", "load_truck", "trench", "grade", "stockpile"]
GROUNDS = ["dry", "wet", "muddy"]
MACHINE_KINDS = ["excavator", "wheel_loader"]

CATEGORIES: dict[str, list[Any]] = {
    "task_type": TASK_TYPES,
    "ground": GROUNDS,
    "machine_kind": MACHINE_KINDS,
}
NUMERIC = ["operator_id", "experience_years", "seq", "start_hour", "temp_c", "rain_mm", "wind_kph"]
FEATURES = list(CATEGORIES) + NUMERIC

QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}
TARGET_DURATION = "duration_min"
TARGET_IDLE = "idle_min"
TARGET_FUEL = "fuel_l"


def calibrated_band(
    p10: np.ndarray, p50: np.ndarray, p90: np.ndarray, margin: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Order independently-fit quantiles and widen the band by the conformal margin."""
    p10 = np.minimum(p10, p50) - margin
    p90 = np.maximum(p90, p50) + margin
    return np.maximum(p10, 0.0), p50, p90


def to_frame(rows: pd.DataFrame | Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Select model features in a fixed order with fixed category levels."""
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
    missing = [c for c in FEATURES if c not in df.columns]
    if missing:
        raise ValueError(f"missing features: {missing}")
    out = df[FEATURES].copy()
    for col, levels in CATEGORIES.items():
        out[col] = pd.Categorical(out[col], categories=levels)
    for col in NUMERIC:
        out[col] = out[col].astype(float)
    return out
