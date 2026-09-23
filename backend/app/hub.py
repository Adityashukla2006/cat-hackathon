"""One live replay per app, broadcast to every connected screen.

The operator tablet, the second machine's tablet, and the supervisor console all watch the same
shift. The first client starts the replay; later clients join it mid-stream. When a replay has
finished (or was stopped), the next client to connect starts a fresh one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy.engine import Engine

from app.db import make_session_factory
from app.replay import ReplayEngine, demo_frames
from app.runtime import ShiftRuntime
from app.schemas import ShadowTimeline, WsReplayStatus

Subscriber = asyncio.Queue[BaseModel]


class ReplayHub:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.subscribers: set[Subscriber] = set()
        self.runtime: ShiftRuntime | None = None
        self.replay: ReplayEngine | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()  # one agent step at a time: minutes and voice notes
        self._start_lock = asyncio.Lock()  # two clients connecting at once start one replay
        self._db = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def subscribe(self) -> Subscriber:
        queue: Subscriber = asyncio.Queue()
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: Subscriber) -> None:
        self.subscribers.discard(queue)

    def broadcast(self, messages: list[BaseModel]) -> None:
        """Push messages to every screen (call from the event loop)."""
        self._broadcast(messages)

    def site_now(self) -> datetime:
        """The latest replay's clock (it stays at the end of a finished replay), else wall clock."""
        if self.runtime is not None and self.runtime.session.now is not None:
            return self.runtime.session.now
        return datetime.now(timezone.utc)

    def mark_pins_changed(self) -> None:
        if self.runtime is not None:
            self.runtime.session.memory["pins_dirty"] = True

    def _broadcast(self, messages: list[BaseModel]) -> None:
        for queue in self.subscribers:
            for message in messages:
                queue.put_nowait(message)

    async def ensure_started(
        self,
        demo: dict[str, Any],
        timeline: ShadowTimeline | None,
        speed: float,
        start: int = 0,
    ) -> bool:
        """Start a replay unless one is already running. Returns True if this call started it."""
        async with self._start_lock:
            if self.running:
                return False
            self._close_db()
            self._db = make_session_factory(self.engine)()
            self.runtime = await asyncio.to_thread(ShiftRuntime, self._db, demo, timeline)
            self.replay = ReplayEngine(demo_frames(demo), speed=speed)
            self._broadcast([WsReplayStatus(state="started", minute=start)])
            self._task = asyncio.create_task(self._run(start))
            return True

    async def _step(self, fn: Callable[..., list[BaseModel]], *args: Any, **kwargs: Any) -> None:
        async with self._lock:
            messages = await asyncio.to_thread(fn, *args, **kwargs)
        self._broadcast(messages)

    async def _run(self, start: int) -> None:
        assert self.replay is not None and self.runtime is not None
        async for minute, frames in self.replay.run(start_minute=start):
            await self._step(self.runtime.process_minute, minute, frames)
        final = self.replay.minute if self.replay.minute is not None else start
        self._broadcast([WsReplayStatus(state="finished", minute=final)])

    async def voice_note(self, transcript: str) -> None:
        if self.runtime is None:
            return
        await self._step(
            self.runtime.voice_note, self.runtime.session.minute, transcript=transcript
        )

    def control(self, action: str) -> None:
        if self.replay is None:
            return
        {"pause": self.replay.pause, "resume": self.replay.resume, "stop": self.replay.stop}.get(
            action, lambda: None
        )()

    async def shutdown(self) -> None:
        if self.replay is not None:
            self.replay.stop()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._close_db()

    def _close_db(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
