"""Record the demo shift's LLM outputs into the committed cache (data/llm_cache.json).

Runs the whole demo once in-process against a throwaway SQLite database: the pre-shift
briefing, the replay with its replan note and incident report, the drills, and the handover.
Every structured output is saved, so later runs replay them with no API calls. Needs
OPENAI_API_KEY. Usage: python -m app.record_cache
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import Shift, make_engine, make_session_factory
from app.llm import CachedLLM, LLMClient, OpenAILLM, set_llm
from app.main import create_app, get_demo_timeline
from app.replay import demo_context, get_demo, load_demo
from app.schemas import WsReplayStatus, parse_ws_message
from app.shadow.predictor import ShadowPredictor, get_predictor

REPLAY_SPEED = 1_000_000  # as fast as the agents can keep up


def run_demo(llm: LLMClient, demo: dict[str, Any], predictor: ShadowPredictor) -> int:
    """Play the demo shift end to end with `llm` and return the stored shift id."""
    engine = make_engine("sqlite://")
    app = create_app(engine)
    app.dependency_overrides[get_demo] = lambda: demo
    app.dependency_overrides[get_predictor] = lambda: predictor
    app.dependency_overrides[get_demo_timeline] = lambda: predictor.predict(demo_context(demo))
    set_llm(llm)
    try:
        with TestClient(app) as client:
            client.get("/demo/plan").raise_for_status()
            with client.websocket_connect(f"/ws/telemetry?speed={REPLAY_SPEED}") as ws:
                while True:
                    msg = parse_ws_message(ws.receive_text())
                    if isinstance(msg, WsReplayStatus) and msg.state == "finished":
                        break
            with make_session_factory(engine)() as db:
                shift_id = db.scalars(select(Shift.id).order_by(Shift.id.desc())).first()
            client.get(f"/shifts/{shift_id}/drills").raise_for_status()
            client.get(f"/shifts/{shift_id}/handover").raise_for_status()
    finally:
        set_llm(None)
        engine.dispose()
    return shift_id


def main() -> None:
    path = get_settings().llm_cache_path
    cache = CachedLLM(OpenAILLM(), path, record=True)
    before = len(cache.entries)
    run_demo(cache, load_demo(), ShadowPredictor.load())
    print(f"{len(cache.entries) - before} new, {len(cache.entries)} total outputs in {path}")


if __name__ == "__main__":
    main()
