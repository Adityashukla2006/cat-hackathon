import asyncio

import pytest

from app.replay import ReplayEngine, demo_frames, load_demo
from app.schemas import TelemetryFrame
from data.generate import generate


def _frame(minute: int, machine_id: int = 1) -> TelemetryFrame:
    return TelemetryFrame(
        shift_id=1,
        machine_id=machine_id,
        minute=minute,
        lat=0.0,
        lon=0.0,
        engine_on=True,
        seatbelt=True,
        idle=False,
        fuel_rate_lph=10.0,
        speed_kph=1.0,
        load_pct=50.0,
    )


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        await asyncio.sleep(0)


async def _collect(engine: ReplayEngine, **kwargs) -> list[tuple[int, list[int]]]:
    return [(m, [f.machine_id for f in fs]) async for m, fs in engine.run(**kwargs)]


def test_streams_minutes_in_order_grouped_by_machine():
    frames = [_frame(2, 2), _frame(0), _frame(1), _frame(2, 1), _frame(0, 2)]
    sleep = FakeSleep()
    out = asyncio.run(_collect(ReplayEngine(frames, sleep=sleep)))
    assert out == [(0, [1, 2]), (1, [1]), (2, [1, 2])]


def test_60x_speed_is_one_second_per_minute():
    sleep = FakeSleep()
    engine = ReplayEngine([_frame(m) for m in range(5)], speed=60, sleep=sleep)
    asyncio.run(_collect(engine))
    assert sleep.calls == [1.0] * 5
    assert ReplayEngine([], speed=120).seconds_per_minute == 0.5
    with pytest.raises(ValueError):
        ReplayEngine([], speed=0)


def test_start_minute_skips_earlier_frames():
    engine = ReplayEngine([_frame(m) for m in range(5)], sleep=FakeSleep())
    assert [m for m, _ in asyncio.run(_collect(engine, start_minute=3))] == [3, 4]
    assert engine.last_minute == 4


def test_pause_blocks_until_resume_and_stop_ends():
    async def scenario() -> list[int]:
        engine = ReplayEngine([_frame(m) for m in range(10)], sleep=FakeSleep())
        seen: list[int] = []

        async def consume() -> None:
            async for minute, _ in engine.run():
                seen.append(minute)
                if minute == 2:
                    engine.pause()

        task = asyncio.create_task(consume())
        for _ in range(20):
            await asyncio.sleep(0)
        assert seen == [0, 1, 2] and engine.paused
        engine.resume()
        while len(seen) < 5:
            await asyncio.sleep(0)
        engine.stop()
        await asyncio.wait_for(task, 1)
        return seen

    seen = asyncio.run(scenario())
    assert seen[:5] == [0, 1, 2, 3, 4]
    assert len(seen) < 10


def test_load_demo_frames(tmp_path):
    generate(seed=42, out_dir=tmp_path, n_shifts=2)
    frames = demo_frames(load_demo(tmp_path / "demo_shift.json"))
    assert len(frames) == 960
    assert ReplayEngine(frames).last_minute == 479


def test_load_demo_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="generate.py"):
        load_demo(tmp_path / "nope.json")
