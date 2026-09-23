import json

import pytest

from app.agents.dispatcher import DispatchNote
from app.agents.drills import DrillContent
from app.agents.handover import HandoverText
from app.llm import CachedLLM, FakeLLM
from app.record_cache import run_demo
from app.schemas import Briefing, IncidentReport, Severity
from data.generate import generate

DEMO_SCHEMAS = {"Briefing", "DispatchNote", "IncidentReport", "DrillContent"}


@pytest.fixture(scope="module")
def demo():
    return generate(seed=42, n_shifts=2)["demo"]


def _scripted() -> FakeLLM:
    return (
        FakeLLM()
        .on(Briefing, Briefing(headline="Wet ramp", key_risks=["soft edge"], focus_tip="Slow"))
        .on(DispatchNote, DispatchNote(explanation="Stockpile first while the ramp dries."))
        .on(
            IncidentReport,
            IncidentReport(
                category="ground",
                summary="Track sank at the ramp edge.",
                severity=Severity.warning,
                hazard_kind="soft_ground",
                actions_taken=["backed off"],
            ),
        )
        .on(
            DrillContent,
            DrillContent(
                scenario="At the ramp",
                question="What now?",
                options=["a", "b", "c"],
                answer=0,
                explanation="Stop and report.",
            ),
        )
        .on(HandoverText, HandoverText(headline="Ramp soft", carry_over=[], watch_outs=[]))
    )


def test_recording_saves_every_demo_output(tmp_path, demo, predictor):
    path = tmp_path / "llm_cache.json"
    run_demo(CachedLLM(_scripted(), path, record=True), demo, predictor)
    saved = {entry["schema"] for entry in json.loads(path.read_text()).values()}
    assert DEMO_SCHEMAS <= saved


def test_second_demo_run_replays_from_the_cache(tmp_path, demo, predictor):
    path = tmp_path / "llm_cache.json"
    run_demo(CachedLLM(_scripted(), path, record=True), demo, predictor)

    silent = FakeLLM()  # nothing registered: a call that reaches it would fall back
    run_demo(CachedLLM(silent, path), demo, predictor)
    reached = {call["schema"].__name__ for call in silent.calls if "schema" in call}
    assert reached.isdisjoint(DEMO_SCHEMAS)
