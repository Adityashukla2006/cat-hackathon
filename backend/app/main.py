import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.planner import PlanResult, plan_shift
from app.agents.scribe import transcribe, write_report
from app.config import get_settings
from app.db import Alert, Incident, Shift, get_engine, init_db, make_session_factory
from app.llm import LLMError
from app.runtime import ShiftRuntime
from app.replay import (
    DEFAULT_SPEED,
    DemoNotGeneratedError,
    ReplayEngine,
    demo_context,
    demo_frames,
    get_demo,
)
from app.schemas import (
    AlertOut,
    HealthOut,
    IncidentCreate,
    IncidentOut,
    ShadowTimeline,
    ShiftContext,
    TranscriptOut,
    WsReplayStatus,
)
from app.shadow.predictor import ModelsNotTrainedError, ShadowPredictor, get_predictor


def get_demo_timeline(demo: dict[str, Any] = Depends(get_demo)) -> ShadowTimeline | None:
    """The demo shift's shadow, or None when the models have not been trained yet."""
    try:
        return get_predictor().predict(demo_context(demo))
    except ModelsNotTrainedError:
        return None


def get_session(request: Request) -> Iterator[Session]:
    session = make_session_factory(request.app.state.engine)()
    try:
        yield session
    finally:
        session.close()


async def _receive_controls(
    ws: WebSocket,
    replay: ReplayEngine,
    on_voice_note: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Client messages: {"action": "pause" | "resume" | "stop"} or
    {"action": "voice_note", "transcript": "..."}."""
    actions = {"pause": replay.pause, "resume": replay.resume, "stop": replay.stop}
    try:
        while True:
            message = await ws.receive_json()
            if not isinstance(message, dict):
                continue
            if message.get("action") == "voice_note" and message.get("transcript"):
                await on_voice_note(message)
            elif action := actions.get(message.get("action")):
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

    @app.get("/demo/plan", response_model=PlanResult)
    def demo_plan(
        request: Request,
        demo: dict[str, Any] = Depends(get_demo),
        shadow: ShadowPredictor = Depends(get_predictor),
    ) -> PlanResult:
        """Scored shadow plus the pre-shift briefing, computed once per process."""
        if getattr(request.app.state, "demo_plan", None) is None:
            ctx = demo_context(demo)
            request.app.state.demo_plan = plan_shift(ctx, shadow.predict(ctx))
        return request.app.state.demo_plan

    @app.get("/shifts/{shift_id}/alerts", response_model=list[AlertOut])
    def list_alerts(shift_id: int, db: Session = Depends(get_session)) -> list[AlertOut]:
        rows = db.scalars(
            select(Alert).where(Alert.shift_id == shift_id).order_by(Alert.minute, Alert.id)
        )
        return [AlertOut.model_validate(r) for r in rows]

    @app.post("/alerts/{alert_id}/ack", response_model=AlertOut)
    def acknowledge_alert(alert_id: int, db: Session = Depends(get_session)) -> AlertOut:
        alert = db.get(Alert, alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="alert not found")
        alert.acknowledged = True
        db.commit()
        return AlertOut.model_validate(alert)

    @app.post("/transcribe", response_model=TranscriptOut)
    async def transcribe_audio(audio: UploadFile = File(...)) -> TranscriptOut:
        data = await audio.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty audio")
        try:
            text_ = await asyncio.to_thread(transcribe, data, audio.filename or "note.webm")
        except LLMError as exc:
            raise HTTPException(status_code=502, detail="transcription unavailable") from exc
        return TranscriptOut(transcript=text_)

    @app.post("/incidents", response_model=IncidentOut, status_code=201)
    def create_incident(body: IncidentCreate, db: Session = Depends(get_session)) -> IncidentOut:
        """Log an incident outside a live replay (the live path goes through the WebSocket)."""
        if db.get(Shift, body.shift_id) is None:
            raise HTTPException(status_code=404, detail="shift not found")
        report, _ = write_report(body.transcript)
        row = Incident(
            shift_id=body.shift_id,
            minute=body.minute,
            transcript=body.transcript,
            report=report.model_dump(mode="json"),
            lat=body.lat,
            lon=body.lon,
        )
        db.add(row)
        db.commit()
        return IncidentOut.model_validate(row)

    @app.websocket("/ws/telemetry")
    async def telemetry_ws(
        ws: WebSocket,
        speed: float = Query(DEFAULT_SPEED, gt=0),
        start: int = Query(0, ge=0),
        demo: dict[str, Any] = Depends(get_demo),
        timeline: ShadowTimeline | None = Depends(get_demo_timeline),
    ) -> None:
        """Stream the demo shift through the agents: telemetry frames, the operator's
        ahead/behind delta, alerts, and replans.

        Clients may send {"action": "pause" | "resume" | "stop"} or a voice note transcript
        {"action": "voice_note", "transcript": "..."} (audio goes through POST /transcribe).
        """
        await ws.accept()
        replay = ReplayEngine(demo_frames(demo), speed=speed)
        db = make_session_factory(ws.app.state.engine)()
        runtime = await asyncio.to_thread(ShiftRuntime, db, demo, timeline)
        lock = asyncio.Lock()  # one agent step at a time: minutes and voice notes share state

        async def run(fn: Callable[..., list], *args: Any, **kwargs: Any) -> None:
            async with lock:
                messages = await asyncio.to_thread(fn, *args, **kwargs)
                for message in messages:
                    await ws.send_text(message.model_dump_json())

        async def on_voice_note(message: dict[str, Any]) -> None:
            await run(runtime.voice_note, runtime.session.minute, transcript=message["transcript"])

        controls = asyncio.create_task(_receive_controls(ws, replay, on_voice_note))
        try:
            await ws.send_text(WsReplayStatus(state="started", minute=start).model_dump_json())
            async for minute, frames in replay.run(start_minute=start):
                await run(runtime.process_minute, minute, frames)
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
            db.close()

    return app


app = create_app()
