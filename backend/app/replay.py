"""Replays recorded telemetry minute by minute. At 60x, one shift minute takes one second."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas import PlannedTask, ShiftContext, TelemetryFrame

DEFAULT_DEMO_PATH = Path(__file__).resolve().parents[1] / "data" / "generated" / "demo_shift.json"
DEFAULT_SPEED = 60.0


class DemoNotGeneratedError(FileNotFoundError):
    pass


def load_demo(path: Path = DEFAULT_DEMO_PATH) -> dict[str, Any]:
    if not path.exists():
        raise DemoNotGeneratedError(f"{path} not found; run `python data/generate.py --seed 42`")
    return json.loads(path.read_text())


@lru_cache
def get_demo() -> dict[str, Any]:
    return load_demo()


def demo_frames(demo: dict[str, Any]) -> list[TelemetryFrame]:
    return [TelemetryFrame.model_validate(f) for f in demo["telemetry"]]


def demo_context(demo: dict[str, Any]) -> ShiftContext:
    """The shadow engine's input for the demo operator's machine."""
    shift = demo["shift"]
    machine = next(m for m in demo["machines"] if m["id"] == shift["machine_id"])
    started = datetime.fromisoformat(shift["started_at"])
    return ShiftContext(
        shift_id=shift["id"],
        operator_id=demo["operator"]["id"],
        experience_years=demo["operator"]["experience_years"],
        machine_kind=machine["kind"],
        ground=shift["site_conditions"]["ground"],
        weather=shift["weather"],
        start_hour=started.hour + started.minute / 60,
        tasks=[
            PlannedTask(
                seq=t["seq"], task_type=t["task_type"], description=t["description"], zone=t["zone"]
            )
            for t in demo["tasks"]
        ],
    )


class ReplayEngine:
    def __init__(
        self,
        frames: Iterable[TelemetryFrame],
        speed: float = DEFAULT_SPEED,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        by_minute: dict[int, list[TelemetryFrame]] = defaultdict(list)
        for frame in frames:
            by_minute[frame.minute].append(frame)
        self._by_minute = {
            m: sorted(fs, key=lambda f: f.machine_id) for m, fs in sorted(by_minute.items())
        }
        self.speed = speed
        self._sleep = sleep
        self._running = asyncio.Event()
        self._running.set()
        self._stopped = False
        self.minute: int | None = None

    @property
    def seconds_per_minute(self) -> float:
        return 60.0 / self.speed

    @property
    def last_minute(self) -> int:
        return max(self._by_minute, default=-1)

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def stop(self) -> None:
        self._stopped = True
        self._running.set()

    async def run(self, start_minute: int = 0) -> AsyncIterator[tuple[int, list[TelemetryFrame]]]:
        """Yield `(minute, frames)` in order, pacing by the replay speed."""
        for minute, frames in self._by_minute.items():
            if minute < start_minute:
                continue
            await self._running.wait()
            if self._stopped:
                return
            self.minute = minute
            yield minute, frames
            await self._sleep(self.seconds_per_minute)
