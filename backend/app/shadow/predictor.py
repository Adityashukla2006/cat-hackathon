"""Shadow prediction service: turns a planned shift into an expected timeline."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import lightgbm as lgb
import numpy as np

from app.schemas import QuantileRange, ShadowTask, ShadowTimeline, ShiftContext
from app.shadow.features import QUANTILES, calibrated_band, to_frame

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "ml" / "models"
MODEL_NAMES = [f"duration_{q}" for q in QUANTILES] + ["idle", "fuel"]
# a task is a risk point when its p90 exceeds its p50 by this share
LONG_TAIL_RATIO = 0.3


class ModelsNotTrainedError(RuntimeError):
    pass


class ShadowPredictor:
    def __init__(self, boosters: dict[str, lgb.Booster], band_margin: float) -> None:
        self.boosters = boosters
        self.band_margin = band_margin

    @classmethod
    def load(cls, model_dir: Path = DEFAULT_MODEL_DIR) -> ShadowPredictor:
        missing = [n for n in MODEL_NAMES if not (model_dir / f"{n}.txt").exists()]
        if missing:
            raise ModelsNotTrainedError(
                f"missing models {missing} in {model_dir}; run `python ml/train.py`"
            )
        boosters = {n: lgb.Booster(model_file=str(model_dir / f"{n}.txt")) for n in MODEL_NAMES}
        calibration = json.loads((model_dir / "calibration.json").read_text())
        return cls(boosters, float(calibration["band_margin_min"]))

    def _predict_task(self, ctx: ShiftContext, seq: int, task_type: str, start_min: float):
        row = {
            "task_type": task_type,
            "ground": ctx.ground,
            "machine_kind": ctx.machine_kind,
            "operator_id": ctx.operator_id,
            "experience_years": ctx.experience_years,
            "seq": seq,
            "start_hour": ctx.start_hour + start_min / 60.0,
            "temp_c": ctx.weather.temp_c,
            "rain_mm": ctx.weather.rain_mm,
            "wind_kph": ctx.weather.wind_kph,
        }
        x = to_frame([row])
        q = {name: self.boosters[f"duration_{name}"].predict(x) for name in QUANTILES}
        p10, p50, p90 = calibrated_band(q["p10"], q["p50"], q["p90"], self.band_margin)
        idle = float(np.clip(self.boosters["idle"].predict(x)[0], 0.0, p50[0]))
        fuel = float(max(self.boosters["fuel"].predict(x)[0], 0.0))
        band = QuantileRange(p10=float(p10[0]), p50=float(p50[0]), p90=float(p90[0]))
        return band, idle, fuel

    def predict(self, ctx: ShiftContext) -> ShadowTimeline:
        """Simulate the shift task by task; each task starts when the previous p50 ends."""
        tasks: list[ShadowTask] = []
        risk_points: list[str] = []
        clock = 0.0
        for planned in sorted(ctx.tasks, key=lambda t: t.seq):
            band, idle, fuel = self._predict_task(ctx, planned.seq, planned.task_type, clock)
            tasks.append(
                ShadowTask(
                    seq=planned.seq,
                    task_type=planned.task_type,
                    description=planned.description,
                    duration_min=band,
                    start_min=round(clock, 2),
                    expected_idle_min=round(idle, 2),
                    expected_fuel_l=round(fuel, 2),
                )
            )
            if band.p90 > band.p50 * (1 + LONG_TAIL_RATIO):
                risk_points.append(
                    f"Task {planned.seq} ({planned.task_type}) could run long: "
                    f"up to {band.p90:.0f} min vs {band.p50:.0f} expected"
                )
            clock += band.p50
        total = QuantileRange(
            p10=sum(t.duration_min.p10 for t in tasks),
            p50=sum(t.duration_min.p50 for t in tasks),
            p90=sum(t.duration_min.p90 for t in tasks),
        )
        return ShadowTimeline(
            shift_id=ctx.shift_id, tasks=tasks, total_min=total, risk_points=risk_points
        )


def schedule_delta(
    timeline: ShadowTimeline, minute: float, task_seq: int, progress_min: float
) -> float:
    """Minutes ahead (+) or behind (-) the shadow.

    `progress_min` is how much of task `task_seq` the real machine has done, in shadow minutes.
    The shadow would reach that point at `start_min + progress`; comparing that with the real
    clock gives the delta. Progress counts up to the task's p50.
    """
    task = next((t for t in timeline.tasks if t.seq == task_seq), None)
    if task is None:
        raise ValueError(f"task {task_seq} is not in the shadow timeline")
    progress = min(max(progress_min, 0.0), task.duration_min.p50)
    return round(task.start_min + progress - minute, 2)


def reorder_timeline(timeline: ShadowTimeline, order: list[int]) -> ShadowTimeline:
    """Same task predictions in a new order, with start times recomputed from the p50s."""
    by_seq = {t.seq: t for t in timeline.tasks}
    if sorted(order) != sorted(by_seq):
        raise ValueError(f"order {order} is not a permutation of {sorted(by_seq)}")
    clock = 0.0
    tasks = []
    for seq in order:
        task = by_seq[seq]
        tasks.append(task.model_copy(update={"start_min": round(clock, 2)}))
        clock += task.duration_min.p50
    return timeline.model_copy(update={"tasks": tasks})


@lru_cache
def get_predictor() -> ShadowPredictor:
    return ShadowPredictor.load()
