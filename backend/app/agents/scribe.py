"""Scribe: turns an operator's voice note into a structured incident report.

The LLM transcribes and structures the note. Two deterministic rails sit around it:
  - a keyword fallback report when the LLM is unavailable
  - a severity floor: anything mentioning an injury is always critical
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.state import GraphState
from app.llm import LLMError, get_llm
from app.schemas import IncidentReport, Severity

SYSTEM_PROMPT = """You turn a heavy-equipment operator's spoken incident note into a report.
Use only what the operator said. Do not guess causes or add details.
category: ground, equipment, near_miss, injury, environment, or other.
summary: one plain sentence saying what happened and where.
severity: critical if anyone was hurt or could have been, warning for hazards that could hurt
someone or damage the machine, info otherwise.
hazard_kind: a short snake_case slug (for example soft_ground, oil_spill, overhead_line) if the
location is now dangerous for other machines, otherwise null.
actions_taken: what the operator said they did, as short items."""

KEYWORDS: list[tuple[str, str, Severity, str | None]] = [
    # (pattern, category, severity, hazard_kind), first match wins
    (
        r"\b(hurt|injur\w*|bleed\w*|ambulance|twist\w*|sprain\w*|fractur\w*|unconscious"
        r"|broke (his|her|my|their) \w+)\b",
        "injury",
        Severity.critical,
        None,
    ),
    (
        r"\b(almost|nearly|near miss|close call|just in time)\b",
        "near_miss",
        Severity.warning,
        None,
    ),
    (
        r"\b(soft|sank|sink\w*|sinking|mud\w*|collaps\w*|edge gave)\b",
        "ground",
        Severity.warning,
        "soft_ground",
    ),
    (
        r"\b(spill\w*|(fuel|oil) on the ground)\b",
        "environment",
        Severity.warning,
        "spill",
    ),
    (
        r"\b(leak\w*|hydraulic|hose|broke\w*|warning light|smoke)\b",
        "equipment",
        Severity.warning,
        None,
    ),
]
INJURY = re.compile(KEYWORDS[0][0], re.IGNORECASE)
ACTION = re.compile(r"\bI ([a-z][^.!?]*)", re.IGNORECASE)


def fallback_report(transcript: str) -> IncidentReport:
    text = transcript.strip()
    category, severity, hazard = "other", Severity.info, None
    for pattern, cat, sev, kind in KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            category, severity, hazard = cat, sev, kind
            break
    first_sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    actions = [f"I {m.strip()}" for m in ACTION.findall(text)]
    return IncidentReport(
        category=category,
        summary=first_sentence[:200],
        severity=severity,
        hazard_kind=hazard,
        actions_taken=actions,
    )


def apply_safety_floor(report: IncidentReport, transcript: str) -> IncidentReport:
    if INJURY.search(transcript) and report.severity != Severity.critical:
        return report.model_copy(update={"severity": Severity.critical})
    return report


def write_report(transcript: str) -> tuple[IncidentReport, str]:
    try:
        report = get_llm().structured(SYSTEM_PROMPT, transcript, IncidentReport)
        source = "llm"
    except LLMError:
        report, source = fallback_report(transcript), "fallback"
    return apply_safety_floor(report, transcript), source


def transcribe(audio: bytes, filename: str = "note.webm") -> str:
    return get_llm().transcribe(audio, filename).strip()


def scribe_node(state: GraphState) -> dict[str, Any]:
    event = state["event"]
    transcript = event.get("transcript")
    if not transcript and event.get("audio"):
        transcript = transcribe(event["audio"])
    if not transcript:
        raise ValueError("voice note has neither a transcript nor audio")
    report, _ = write_report(transcript)
    return {"incident": report, "transcript": transcript}
