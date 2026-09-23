import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import Depends, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import get_engine, init_db
from app.replay import (
    DEFAULT_SPEED,
    DemoNotGeneratedError,
    ReplayEngine,
    demo_context,
    demo_frames,
    get_demo,
)
from app.schemas import (
    HealthOut,
    ShadowTimeline,
    ShiftContext,
    WsReplayStatus,
    WsShadowDelta,
    WsTelemetry,
)
from app.shadow.predictor import ModelsNotTrainedError, ShadowPredictor, get_predictor
from app.shadow.tracker import ShadowTracker


def get_demo_timeline(demo: dict[str, Any] = Depends(get_demo)) -> ShadowTimeline | None:
    """The demo shift's shadow, or None when the models have not been trained yet."""
    try:
        return get_predictor().predict(demo_context(demo))
    except ModelsNotTrainedError:
        return None


async def _receive_controls(ws: WebSocket, replay: ReplayEngine) -> None:
    actions = {"pause": replay.pause, "resume": replay.resume, "stop": replay.stop}
    try:
        while True:
            message = await ws.receive_json()
            action = actions.get(message.get("action")) if isinstance(message, dict) else None
            if action:
                action()
    except WebSocketDisconnect:
        replay.stop()


def create_app(engine: Engine | None = None) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine or get_engine()
        init_db(app.state.engine)
        yield

    app = FastAPI(title="Shadow Shift", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ModelsNotTrainedError)
    @app.exception_handler(DemoNotGeneratedError)
    def not_ready(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/health", response_model=HealthOut)
    def health(request: Request) -> HealthOut:
        try:
            with request.app.state.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except SQLAlchemyError:
            db_ok = False
        return HealthOut(status="ok" if db_ok else "degraded", database=db_ok)

    @app.post("/shadow/predict", response_model=ShadowTimeline)
    def predict_shadow(
        ctx: ShiftContext, shadow: ShadowPredictor = Depends(get_predictor)
    ) -> ShadowTimeline:
        return shadow.predict(ctx)

    @app.get("/demo/shadow", response_model=ShadowTimeline)
    def demo_shadow(
        demo: dict[str, Any] = Depends(get_demo), shadow: ShadowPredictor = Depends(get_predictor)
    ) -> ShadowTimeline:
        return shadow.predict(demo_context(demo))

    @app.websocket("/ws/telemetry")
    async def telemetry_ws(
        ws: WebSocket,
        speed: float = Query(DEFAULT_SPEED, gt=0),
        start: int = Query(0, ge=0),
        demo: dict[str, Any] = Depends(get_demo),
        timeline: ShadowTimeline | None = Depends(get_demo_timeline),
    ) -> None:
        """Stream the demo shift: telemetry frames plus the operator's ahead/behind delta.

        Clients may send {"action": "pause" | "resume" | "stop"}.
        """
        await ws.accept()
        replay = ReplayEngine(demo_frames(demo), speed=speed)
        tracker = ShadowTracker(timeline, demo["shift"]["machine_id"]) if timeline else None
        controls = asyncio.create_task(_receive_controls(ws, replay))
        try:
            await ws.send_text(WsReplayStatus(state="started", minute=start).model_dump_json())
            async for minute, frames in replay.run(start_minute=start):
                for frame in frames:
                    await ws.send_text(WsTelemetry(frame=frame).model_dump_json())
                    delta = tracker.update(frame) if tracker else None
                    if delta is not None:
                        msg = WsShadowDelta(minute=minute, delta_min=delta)
                        await ws.send_text(msg.model_dump_json())
            final = replay.minute if replay.minute is not None else start
            await ws.send_text(WsReplayStatus(state="finished", minute=final).model_dump_json())
            await ws.close()
        except WebSocketDisconnect:
            pass
        finally:
            replay.stop()
            controls.cancel()
            with suppress(asyncio.CancelledError):
                await controls

    return app


app = create_app()
