import asyncio
from collections.abc import AsyncIterator, Iterator
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

from app.agents.assistant import answer as assistant_answer
from app.agents.planner import PlanResult, plan_shift
from app.agents.scribe import transcribe, write_report
from app.config import get_settings
from app.db import (
    Alert,
    HazardPin,
    Incident,
    Shift,
    get_engine,
    init_db,
    make_session_factory,
)
from app.llm import LLMError
from app.hub import ReplayHub
from app.replay import DEFAULT_SPEED, DemoNotGeneratedError, demo_context, get_demo
from app.retrieval import GuideIndex, get_guide_index
from app.schemas import (
    AlertOut,
    ChatAnswer,
    ChatRequest,
    GuideHitOut,
    HazardPinOut,
    HealthOut,
    IncidentCreate,
    IncidentOut,
    ShadowTimeline,
    ShiftContext,
    TranscriptOut,
    WsHazardPin,
    WsReplayStatus,
)
from app.shadow.predictor import ModelsNotTrainedError, ShadowPredictor, get_predictor
from app.site_memory import active_pins, clear, pin_out, reconfirm


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


async def _receive_controls(ws: WebSocket, hub: ReplayHub) -> None:
    """Client messages: {"action": "pause" | "resume" | "stop"} or
    {"action": "voice_note", "transcript": "..."}. Returns when the client disconnects."""
    with suppress(WebSocketDisconnect):
        while True:
            message = await ws.receive_json()
            if not isinstance(message, dict):
                continue
            if message.get("action") == "voice_note" and message.get("transcript"):
                await hub.voice_note(message["transcript"])
            elif isinstance(message.get("action"), str):
                hub.control(message["action"])


async def _forward(ws: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        message = await queue.get()
        await ws.send_text(message.model_dump_json())
        if isinstance(message, WsReplayStatus) and message.state == "finished":
            await ws.close()
            return


def create_app(engine: Engine | None = None) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine or get_engine()
        init_db(app.state.engine)
        app.state.hub = ReplayHub(app.state.engine)
        yield
        await app.state.hub.shutdown()

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

    @app.get("/guides/search", response_model=list[GuideHitOut])
    def search_guides(
        q: str = Query(min_length=2, max_length=300),
        k: int = Query(3, ge=1, le=10),
        index: GuideIndex = Depends(get_guide_index),
    ) -> list[GuideHitOut]:
        return [
            GuideHitOut(
                guide_id=h.section.guide_id, source=h.source, text=h.section.text, score=h.score
            )
            for h in index.search(q, k=k)
        ]

    @app.post("/chat", response_model=ChatAnswer)
    async def chat(
        body: ChatRequest, request: Request, index: GuideIndex = Depends(get_guide_index)
    ) -> ChatAnswer:
        """The operator's chatbot. Uses the live shift when a replay is running."""
        hub: ReplayHub = request.app.state.hub
        session = hub.runtime.session if hub.runtime is not None and hub.running else None
        return await asyncio.to_thread(assistant_answer, body.message, session, index)

    @app.get("/hazards", response_model=list[HazardPinOut])
    def list_hazards(request: Request, db: Session = Depends(get_session)) -> list[HazardPinOut]:
        """Active hazard pins with confidence decayed to the site clock."""
        return active_pins(db, request.app.state.hub.site_now())

    async def _update_pin(request: Request, db: Session, pin_id: int, action: str) -> HazardPinOut:
        hub: ReplayHub = request.app.state.hub
        pin = db.get(HazardPin, pin_id)
        if pin is None:
            raise HTTPException(status_code=404, detail="hazard not found")
        now = hub.site_now()
        if action == "confirm":
            reconfirm(db, pin, now)
        else:
            clear(db, pin)
        out = pin_out(pin, now)
        hub.mark_pins_changed()
        hub.broadcast([WsHazardPin(pin=out, created=False)])
        return out

    @app.post("/hazards/{pin_id}/confirm", response_model=HazardPinOut)
    async def confirm_hazard(
        pin_id: int, request: Request, db: Session = Depends(get_session)
    ) -> HazardPinOut:
        return await _update_pin(request, db, pin_id, "confirm")

    @app.post("/hazards/{pin_id}/clear", response_model=HazardPinOut)
    async def clear_hazard(
        pin_id: int, request: Request, db: Session = Depends(get_session)
    ) -> HazardPinOut:
        return await _update_pin(request, db, pin_id, "clear")

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
        """Stream the live demo shift: telemetry frames, the operator's ahead/behind delta,
        alerts, replans, and incidents. All clients share one replay (see app/hub.py); the first
        client's `speed` and `start` decide how it runs.

        Clients may send {"action": "pause" | "resume" | "stop"} or a voice note transcript
        {"action": "voice_note", "transcript": "..."} (audio goes through POST /transcribe).
        """
        await ws.accept()
        hub: ReplayHub = ws.app.state.hub
        queue = hub.subscribe()
        tasks = [
            asyncio.create_task(_receive_controls(ws, hub)),
            asyncio.create_task(_forward(ws, queue)),
        ]
        try:
            await hub.ensure_started(demo, timeline, speed, start)
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(queue)
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                    await task

    return app


app = create_app()
