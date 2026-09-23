"""Synthetic data generator: shift history for training plus the scripted demo shift.

Usage: python data/generate.py --seed 42 [--out data/generated]

Writes:
  history.csv      one row per completed task across past shifts (model training data)
  operators.json   operator roster
  demo_shift.json  the scripted demo shift, minute-by-minute telemetry for two machines
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.geo import offset  # noqa: E402
from app.shadow.features import GROUNDS, TASK_TYPES  # noqa: E402

SITE_CENTER = (40.6950, -89.5890)
# zone name -> (north_m, east_m) from the site center
ZONES: dict[str, tuple[float, float]] = {
    "pit": (0.0, 0.0),
    "ramp": (120.0, 60.0),
    "trench": (60.0, -150.0),
    "stockpile": (-150.0, 100.0),
    "dump": (-200.0, -120.0),
    "yard": (250.0, 250.0),
}


BASE_MIN = {"dig": 45.0, "load_truck": 40.0, "trench": 55.0, "grade": 50.0, "stockpile": 50.0}
FUEL_LPH = {"dig": 22.0, "load_truck": 20.0, "trench": 18.0, "grade": 16.0, "stockpile": 19.0}
LOAD_PCT = {"dig": 75.0, "load_truck": 65.0, "trench": 60.0, "grade": 45.0, "stockpile": 55.0}
IDLE_FUEL_LPH = 4.0

GROUND_FACTOR = {"dry": 1.0, "wet": 1.12, "muddy": 1.3}
MACHINE_FACTOR = {"excavator": 1.0, "wheel_loader": 0.9}

OPERATORS: list[dict[str, Any]] = [
    {"id": 1, "name": "Sam Rivera", "experience_years": 2.5, "skill": 1.08},
    {"id": 2, "name": "Priya Nair", "experience_years": 9.0, "skill": 0.92},
    {"id": 3, "name": "Luis Ortega", "experience_years": 5.0, "skill": 1.0},
    {"id": 4, "name": "Dana Kim", "experience_years": 1.0, "skill": 1.12},
    {"id": 5, "name": "Marcus Bell", "experience_years": 14.0, "skill": 0.9},
    {"id": 6, "name": "Aisha Okafor", "experience_years": 3.5, "skill": 1.02},
]

MACHINES: list[dict[str, Any]] = [
    {"id": 1, "name": "EX-01", "model": "CAT 320", "kind": "excavator"},
    {"id": 2, "name": "WL-02", "model": "CAT 950", "kind": "wheel_loader"},
]

SHIFT_MINUTES = 480

# Minutes at which the demo shift's scripted events happen. Integration tests key off these.
DEMO_SCRIPT: dict[str, Any] = {
    "engine_on_minute": 2,
    "seatbelt_unbuckled": [2, 5],  # inclusive range, engine on, belt off
    "idle_window": [150, 174],  # unplanned idle during task 3, on the ramp
    "incident_minute": 200,
    "incident_transcript": (
        "Ground is soft at the edge of the haul ramp, right track sank about a foot. "
        "I backed off and stopped work there."
    ),
    "second_machine_approach": [250, 259],  # WL-02 drives towards the ramp
    "second_machine_at_hazard": [260, 275],
    "fatigue_from_minute": 420,
}

DEMO_WEATHER = {"temp_c": 14.0, "rain_mm": 4.0, "wind_kph": 18.0, "ground": "wet"}

# (seq, task_type, description, zone, pace vs the ground-truth duration)
DEMO_TASKS: list[tuple[int, str, str, str, float]] = [
    (1, "dig", "Dig pit face A", "pit", 0.97),
    (2, "load_truck", "Load haul trucks at the pit", "pit", 1.0),
    (3, "trench", "Cut drainage ditch along the haul ramp", "ramp", 1.0),
    (4, "load_truck", "Load haul trucks at the pit", "pit", 1.0),  # runs to shift end
    (5, "grade", "Grade the yard pad", "yard", 1.0),
    (6, "stockpile", "Build stockpile from pit spoil", "stockpile", 1.02),
]
# The operator follows the Dispatcher's replan after the idle window: riskier tasks 6 and 5
# move ahead of the truck loading. Integration tests check the Dispatcher recommends this.
DEMO_EXECUTION_ORDER = [1, 2, 3, 6, 5, 4]
DEMO_FIRST_TASK_MINUTE = 7


def zone_point(zone: str) -> tuple[float, float]:
    north, east = ZONES[zone]
    return offset(*SITE_CENTER, north, east)


def expected_duration(
    task_type: str,
    experience_years: float,
    skill: float,
    machine_kind: str,
    ground: str,
    rain_mm: float,
    start_hour: float,
) -> float:
    """Noise-free ground-truth duration used by the generator."""
    exp_factor = 1.25 - 0.035 * min(experience_years, 10.0)
    fatigue = 1.0 + 0.03 * max(0.0, start_hour - 11.0)
    return (
        BASE_MIN[task_type]
        * exp_factor
        * skill
        * MACHINE_FACTOR[machine_kind]
        * GROUND_FACTOR[ground]
        * (1.0 + 0.02 * rain_mm)
        * fatigue
    )


def demo_schedule() -> dict[int, tuple[int, int]]:
    """seq -> (start_minute, minutes) for each demo task, in execution order.

    Tasks run at their scripted pace against the ground-truth duration for the demo operator.
    Task 3 also contains the unplanned idle window, and the last task runs on to the shift end
    because fatigue slows it down.
    """
    op = OPERATORS[0]
    tasks = {t[0]: t for t in DEMO_TASKS}
    idle_lo, idle_hi = DEMO_SCRIPT["idle_window"]
    schedule: dict[int, tuple[int, int]] = {}
    clock = DEMO_FIRST_TASK_MINUTE
    for i, seq in enumerate(DEMO_EXECUTION_ORDER):
        _, task_type, _desc, _zone, pace = tasks[seq]
        if i == len(DEMO_EXECUTION_ORDER) - 1:
            minutes = SHIFT_MINUTES - clock
        else:
            truth = expected_duration(
                task_type,
                op["experience_years"],
                op["skill"],
                "excavator",
                DEMO_WEATHER["ground"],
                DEMO_WEATHER["rain_mm"],
                7.0 + clock / 60.0,
            )
            minutes = round(truth * pace)
            if seq == 3:
                minutes += idle_hi - idle_lo + 1
        schedule[seq] = (clock, minutes)
        clock += minutes
    return schedule


def make_history(rng: np.random.Generator, n_shifts: int = 300) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for shift_id in range(1, n_shifts + 1):
        op = OPERATORS[rng.integers(len(OPERATORS))]
        machine = MACHINES[rng.integers(len(MACHINES))]
        ground = GROUNDS[rng.choice(3, p=[0.55, 0.3, 0.15])]
        rain_mm = float(rng.gamma(1.2, 2.0)) if ground != "dry" else 0.0
        temp_c = float(rng.normal(16, 8))
        wind_kph = float(abs(rng.normal(12, 7)))
        minute = 0.0
        for seq in range(1, int(rng.integers(6, 10)) + 1):
            task_type = TASK_TYPES[rng.integers(len(TASK_TYPES))]
            start_hour = 7.0 + minute / 60.0
            base = expected_duration(
                task_type,
                op["experience_years"],
                op["skill"],
                machine["kind"],
                ground,
                rain_mm,
                start_hour,
            )
            duration = base * float(rng.lognormal(0.0, 0.12))
            idle_share = 0.06 + 0.02 * GROUNDS.index(ground) + 0.01 * rain_mm
            idle = min(duration * 0.6, duration * idle_share * float(rng.lognormal(0.0, 0.3)))
            fuel = (duration - idle) / 60.0 * FUEL_LPH[task_type] * float(
                rng.lognormal(0.0, 0.08)
            ) + idle / 60.0 * IDLE_FUEL_LPH
            rows.append(
                {
                    "shift_id": shift_id,
                    "operator_id": op["id"],
                    "experience_years": op["experience_years"],
                    "machine_kind": machine["kind"],
                    "task_type": task_type,
                    "seq": seq,
                    "start_hour": round(start_hour, 3),
                    "temp_c": round(temp_c, 1),
                    "rain_mm": round(rain_mm, 2),
                    "wind_kph": round(wind_kph, 1),
                    "ground": ground,
                    "duration_min": round(duration, 2),
                    "idle_min": round(idle, 2),
                    "fuel_l": round(fuel, 2),
                }
            )
            minute += duration
    return pd.DataFrame(rows)


def _frame(
    machine_id: int,
    minute: int,
    point: tuple[float, float],
    *,
    engine_on: bool = True,
    seatbelt: bool = True,
    idle: bool = False,
    fuel: float = 0.0,
    speed: float = 0.0,
    load: float = 0.0,
    task_seq: int | None = None,
) -> dict[str, Any]:
    return {
        "shift_id": 1,
        "machine_id": machine_id,
        "minute": minute,
        "lat": round(point[0], 7),
        "lon": round(point[1], 7),
        "engine_on": engine_on,
        "seatbelt": seatbelt,
        "idle": idle,
        "fuel_rate_lph": round(max(fuel, 0.0), 2),
        "speed_kph": round(max(speed, 0.0), 2),
        "load_pct": round(min(max(load, 0.0), 100.0), 1),
        "task_seq": task_seq,
    }


def _jitter(rng: np.random.Generator, point: tuple[float, float], meters: float):
    return offset(point[0], point[1], *rng.normal(0.0, meters, size=2))


def _demo_ex01(rng: np.random.Generator) -> list[dict[str, Any]]:
    s = DEMO_SCRIPT
    frames: list[dict[str, Any]] = []
    pit = zone_point("pit")
    belt_lo, belt_hi = s["seatbelt_unbuckled"]
    for minute in range(DEMO_FIRST_TASK_MINUTE):
        engine = minute >= s["engine_on_minute"]
        frames.append(
            _frame(
                1,
                minute,
                pit,
                engine_on=engine,
                seatbelt=not (belt_lo <= minute <= belt_hi),
                idle=engine,
                fuel=IDLE_FUEL_LPH if engine else 0.0,
            )
        )
    minute = DEMO_FIRST_TASK_MINUTE
    idle_lo, idle_hi = s["idle_window"]
    tasks = {t[0]: t for t in DEMO_TASKS}
    schedule = demo_schedule()
    for seq in DEMO_EXECUTION_ORDER:
        _, task_type, _desc, zone, _pace = tasks[seq]
        minutes = schedule[seq][1]
        center = zone_point(zone)
        for _ in range(minutes):
            fatigue = minute >= s["fatigue_from_minute"]
            if idle_lo <= minute <= idle_hi:
                frames.append(
                    _frame(1, minute, center, idle=True, fuel=IDLE_FUEL_LPH, task_seq=seq)
                )
            else:
                idle = bool(rng.random() < (0.15 if fatigue else 0.06))
                load = LOAD_PCT[task_type] * (0.8 if fatigue else 1.0) + rng.normal(0, 6)
                frames.append(
                    _frame(
                        1,
                        minute,
                        _jitter(rng, center, 6.0),
                        idle=idle,
                        fuel=IDLE_FUEL_LPH if idle else FUEL_LPH[task_type] + rng.normal(0, 1.5),
                        speed=0.0 if idle else abs(rng.normal(2.0, 1.0)),
                        load=0.0 if idle else load,
                        task_seq=seq,
                    )
                )
            minute += 1
    assert minute == SHIFT_MINUTES, minute
    return frames


def _lerp(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _demo_wl02(rng: np.random.Generator) -> list[dict[str, Any]]:
    s = DEMO_SCRIPT
    stockpile, dump, ramp = zone_point("stockpile"), zone_point("dump"), zone_point("ramp")
    app_lo, app_hi = s["second_machine_approach"]
    at_lo, at_hi = s["second_machine_at_hazard"]
    frames: list[dict[str, Any]] = []
    for minute in range(SHIFT_MINUTES):
        if app_lo <= minute <= app_hi:
            t = (minute - app_lo + 1) / (app_hi - app_lo + 2)
            point, speed, load = _lerp(dump, ramp, t), 12.0, 30.0
        elif at_lo <= minute <= at_hi:
            point, speed, load = _jitter(rng, ramp, 3.0), 3.0, 60.0
        elif at_hi < minute <= at_hi + 10:
            t = (minute - at_hi) / 11
            point, speed, load = _lerp(ramp, stockpile, t), 12.0, 30.0
        else:
            # 20-minute stockpile <-> dump haul cycle
            phase = (minute % 20) / 20
            t = phase * 2 if phase < 0.5 else (1 - phase) * 2
            point = _jitter(rng, _lerp(stockpile, dump, t), 2.0)
            speed, load = 14.0 + rng.normal(0, 2), 70.0 if phase < 0.5 else 20.0
        frames.append(
            _frame(2, minute, point, fuel=17.0 + rng.normal(0, 1.5), speed=speed, load=load)
        )
    return frames


def make_demo_shift(rng: np.random.Generator) -> dict[str, Any]:
    ex01, wl02 = _demo_ex01(rng), _demo_wl02(rng)
    incident_frame = ex01[DEMO_SCRIPT["incident_minute"]]
    telemetry = sorted(ex01 + wl02, key=lambda f: (f["minute"], f["machine_id"]))
    return {
        "shift": {
            "id": 1,
            "operator_id": 1,
            "machine_id": 1,
            "started_at": "2026-09-23T07:00:00+00:00",
            "weather": {k: v for k, v in DEMO_WEATHER.items() if k != "ground"},
            "site_conditions": {"ground": DEMO_WEATHER["ground"]},
        },
        "operator": {k: v for k, v in OPERATORS[0].items() if k != "skill"},
        "machines": MACHINES,
        "tasks": [
            {
                "seq": seq,
                "task_type": task_type,
                "description": desc,
                "zone": zone,
                "actual_start_min": start,
                "actual_min": minutes,
            }
            for (seq, task_type, desc, zone, _pace), (start, minutes) in zip(
                DEMO_TASKS, (demo_schedule()[t[0]] for t in DEMO_TASKS)
            )
        ],
        "execution_order": DEMO_EXECUTION_ORDER,
        "script": DEMO_SCRIPT,
        "incident": {
            "minute": DEMO_SCRIPT["incident_minute"],
            "transcript": DEMO_SCRIPT["incident_transcript"],
            "lat": incident_frame["lat"],
            "lon": incident_frame["lon"],
        },
        "telemetry": telemetry,
    }


def generate(seed: int = 42, out_dir: Path | None = None, n_shifts: int = 300) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    history = make_history(rng, n_shifts)
    demo = make_demo_shift(np.random.default_rng(seed))
    roster = [{k: v for k, v in op.items() if k != "skill"} for op in OPERATORS]
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        history.to_csv(out_dir / "history.csv", index=False)
        (out_dir / "operators.json").write_text(json.dumps(roster, indent=2))
        (out_dir / "demo_shift.json").write_text(json.dumps(demo))
    return {"history": history, "demo": demo, "operators": roster}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--shifts", type=int, default=300)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "generated")
    args = parser.parse_args()
    result = generate(args.seed, args.out, args.shifts)
    print(
        f"wrote {len(result['history'])} task rows and "
        f"{len(result['demo']['telemetry'])} demo frames to {args.out}"
    )


if __name__ == "__main__":
    main()
