import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timezone
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
from app.agents.coach import CoachAdvice, advise
from app.agents.drills import Drill, drills_for_shift, shift_moments
from app.agents.handover import Handover, build_handover
from app.agents.planner import PlanResult, plan_shift
from app import booking, training
from app.guides import get_guides
from app.runtime import seed_people
from app.agents.scribe import transcribe, write_report
from app.config import get_settings
from app.db import (
    Alert,
    Booking,
    HazardPin,
    Incident,
    Operator,
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
    BookingCreate,
    BookingOut,
    SlotOut,
    ChatAnswer,
    ChatRequest,
    DrillAnswerIn,
    DrillOut,
    DrillResultOut,
    GuideHitOut,
    GuideOut,
    GuideSectionOut,
    LessonOut,
    LessonSummary,
    ModuleOut,
    QuizQuestionOut,
    QuizSubmit,
    TrainingResultIn,
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
        app.state.drills = {}
        with suppress(DemoNotGeneratedError), make_session_factory(app.state.engine)() as db:
            seed_people(db, get_demo())  # the demo operator can train before any replay
            db.commit()
        yield
        await app.state.hub.shutdown()

    app = FastAPI(title="Shadow Shift", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.frontend_origin_regex,
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

    @app.get("/shifts/{shift_id}/incidents", response_model=list[IncidentOut])
    def list_incidents(shift_id: int, db: Session = Depends(get_session)) -> list[IncidentOut]:
        rows = db.scalars(
            select(Incident).where(Incident.shift_id == shift_id).order_by(Incident.minute)
        )
        return [IncidentOut.model_validate(r) for r in rows]

    @app.get("/shifts/{shift_id}/handover", response_model=Handover)
    async def shift_handover(
        shift_id: int, request: Request, db: Session = Depends(get_session)
    ) -> Handover:
        """End-of-shift handover. Uses the live (or just-finished) replay when it's this shift."""
        hub: ReplayHub = request.app.state.hub
        runtime = hub.runtime
        session = runtime.session if runtime and runtime.session.shift_id == shift_id else None
        try:
            return await asyncio.to_thread(build_handover, db, shift_id, hub.site_now(), session)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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

    @app.get("/guides/{guide_id}", response_model=GuideOut)
    def read_guide(guide_id: str) -> GuideOut:
        guide = next((g for g in get_guides() if g.id == guide_id), None)
        if guide is None:
            raise HTTPException(status_code=404, detail="guide not found")
        return GuideOut(
            id=guide.id,
            title=guide.title,
            sections=[GuideSectionOut(heading=s.heading, text=s.text) for s in guide.sections],
        )

    def _require_operator(db: Session, operator_id: int) -> None:
        if db.get(Operator, operator_id) is None:
            raise HTTPException(status_code=404, detail="operator not found")

    @app.get("/training/modules", response_model=list[ModuleOut])
    def training_modules(operator_id: int, db: Session = Depends(get_session)) -> list[ModuleOut]:
        best = training.best_scores(db, operator_id)
        return [
            ModuleOut(
                id=m.id,
                title=m.title,
                lessons=[
                    LessonSummary(
                        id=lesson.id,
                        title=lesson.title,
                        guide_id=lesson.guide_id,
                        practice=lesson.practice,
                        best_score=best.get(lesson.id),
                        passed=best.get(lesson.id, 0.0) >= training.PASS_SCORE,
                    )
                    for lesson in m.lessons
                ],
            )
            for m in training.CURRICULUM
        ]

    @app.get("/training/lessons/{lesson_id}", response_model=LessonOut)
    def training_lesson(lesson_id: str) -> LessonOut:
        lesson = training.LESSONS.get(lesson_id)
        if lesson is None:
            raise HTTPException(status_code=404, detail="lesson not found")
        return LessonOut(
            id=lesson.id,
            title=lesson.title,
            guide_id=lesson.guide_id,
            key_points=lesson.key_points,
            practice=lesson.practice,
            questions=[
                QuizQuestionOut(question=q.question, options=q.options) for q in lesson.quiz
            ],
        )

    @app.post("/training/lessons/{lesson_id}/quiz", response_model=training.QuizResult)
    def submit_quiz(
        lesson_id: str, body: QuizSubmit, db: Session = Depends(get_session)
    ) -> training.QuizResult:
        lesson = training.LESSONS.get(lesson_id)
        if lesson is None:
            raise HTTPException(status_code=404, detail="lesson not found")
        _require_operator(db, body.operator_id)
        try:
            result = training.grade(lesson, body.answers)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        training.record_result(db, body.operator_id, lesson.id, result.score)
        return result

    @app.post("/training/results", status_code=201)
    def record_training_result(
        body: TrainingResultIn, db: Session = Depends(get_session)
    ) -> dict[str, str]:
        """Simulator, walkaround, and drill scores (0-1) for the Coach to learn from."""
        _require_operator(db, body.operator_id)
        training.record_result(db, body.operator_id, body.activity_id, body.score)
        return {"status": "recorded"}

    def _drills(request: Request, db: Session, shift_id: int) -> dict[str, Drill]:
        """Drills for a shift, regenerated only when the shift's moments change."""
        key = (shift_id, tuple(shift_moments(db, shift_id)))
        cache: dict = request.app.state.drills
        if cache.get(shift_id, (None,))[0] != key:
            cache[shift_id] = (key, {d.id: d for d in drills_for_shift(db, shift_id)})
        return cache[shift_id][1]

    @app.get("/shifts/{shift_id}/drills", response_model=list[DrillOut])
    async def shift_drills(
        shift_id: int, request: Request, db: Session = Depends(get_session)
    ) -> list[DrillOut]:
        drills = await asyncio.to_thread(_drills, request, db, shift_id)
        return [
            DrillOut(
                id=d.id,
                kind=d.kind,
                minute=d.minute,
                title=d.title,
                lesson_id=d.lesson_id,
                practice=d.practice,
                scenario=d.content.scenario,
                question=d.content.question,
                options=d.content.options,
            )
            for d in drills.values()
        ]

    @app.post("/shifts/{shift_id}/drills/{drill_id}/answer", response_model=DrillResultOut)
    def answer_drill(
        shift_id: int,
        drill_id: str,
        body: DrillAnswerIn,
        request: Request,
        db: Session = Depends(get_session),
    ) -> DrillResultOut:
        drill = request.app.state.drills.get(shift_id, (None, {}))[1].get(drill_id)
        if drill is None:
            raise HTTPException(status_code=404, detail="drill not found; list drills first")
        _require_operator(db, body.operator_id)
        correct = body.answer == drill.content.answer
        training.record_result(db, body.operator_id, f"drill:{drill.kind}", float(correct))
        return DrillResultOut(
            correct=correct,
            correct_option=drill.content.options[drill.content.answer],
            explanation=drill.content.explanation,
        )

    @app.get("/operators/{operator_id}/coach", response_model=CoachAdvice)
    async def coach(operator_id: int, db: Session = Depends(get_session)) -> CoachAdvice:
        _require_operator(db, operator_id)
        return await asyncio.to_thread(advise, db, operator_id)

    @app.get("/instructors/slots", response_model=list[SlotOut])
    def instructor_slots(
        topic: str,
        start: date | None = None,
        days: int = Query(5, ge=1, le=14),
        db: Session = Depends(get_session),
    ) -> list[SlotOut]:
        """Free slots for instructors who teach `topic`, from `start` (default: tomorrow)."""
        if topic not in training.LESSONS:
            raise HTTPException(status_code=404, detail="unknown topic")
        start = start or date.fromordinal(datetime.now(timezone.utc).date().toordinal() + 1)
        return [
            SlotOut(instructor=name, slot_start=slot)
            for name, slot in booking.open_slots(db, topic, start, days)
        ]

    @app.post("/bookings", response_model=BookingOut, status_code=201)
    def create_booking(body: BookingCreate, db: Session = Depends(get_session)) -> BookingOut:
        _require_operator(db, body.operator_id)
        if body.topic not in training.LESSONS:
            raise HTTPException(status_code=404, detail="unknown topic")
        try:
            row = booking.book(db, body.operator_id, body.topic, body.slot_start, body.instructor)
        except booking.SlotTakenError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return BookingOut.model_validate(row)

    @app.get("/operators/{operator_id}/bookings", response_model=list[BookingOut])
    def operator_bookings(operator_id: int, db: Session = Depends(get_session)) -> list[BookingOut]:
        rows = db.scalars(
            select(Booking)
            .where(Booking.operator_id == operator_id, Booking.status == "confirmed")
            .order_by(Booking.slot_start)
        )
        return [BookingOut.model_validate(r) for r in rows]

    @app.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
    def cancel_booking(booking_id: int, db: Session = Depends(get_session)) -> BookingOut:
        row = db.get(Booking, booking_id)
        if row is None:
            raise HTTPException(status_code=404, detail="booking not found")
        return BookingOut.model_validate(booking.cancel(db, row))

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

        CORS does not cover WebSockets, so browser origins are checked here. Clients that
        send no Origin (scripts, tests) are let through.
        """
        origin = ws.headers.get("origin")
        if origin is not None and not settings.origin_allowed(origin):
            await ws.close(code=1008)
            return
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
