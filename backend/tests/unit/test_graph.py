import pytest

from app.agents.state import AlertDraft, ShiftSession
from app.graph import build_graph, run_event
from app.schemas import AlertKind, Severity, ShiftContext


def _session() -> ShiftSession:
    ctx = ShiftContext.model_validate(
        {
            "shift_id": 1,
            "operator_id": 1,
            "experience_years": 2.5,
            "machine_kind": "excavator",
            "ground": "wet",
            "weather": {"temp_c": 14, "rain_mm": 4, "wind_kph": 18},
            "tasks": [
                {"seq": 2, "task_type": "load_truck", "description": "Load"},
                {"seq": 1, "task_type": "dig", "description": "Dig"},
            ],
        }
    )
    return ShiftSession(shift_id=1, machine_id=1, context=ctx)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def node(self, name: str, update: dict | None = None):
        def fn(state):
            self.calls.append(name)
            return update or {}

        return fn


def test_session_defaults_task_order_by_seq():
    assert _session().task_order == [1, 2]
    assert _session().me is None


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("plan", ["planner"]), ("voice_note", ["scribe"]), ("telemetry", ["sentinel"])],
)
def test_events_route_to_their_agent(kind, expected):
    rec = Recorder()
    graph = build_graph(
        planner=rec.node("planner"),
        sentinel=rec.node("sentinel"),
        dispatcher=rec.node("dispatcher"),
        scribe=rec.node("scribe"),
    )
    run_event(graph, _session(), {"kind": kind, "minute": 0})
    assert rec.calls == expected


def test_sentinel_hands_off_to_dispatcher_when_replan_needed():
    rec = Recorder()
    alert = AlertDraft(10, AlertKind.idle_deviation, Severity.warning, "Idle too long")
    graph = build_graph(
        sentinel=rec.node("sentinel", {"alerts": [alert], "needs_replan": True}),
        dispatcher=rec.node("dispatcher"),
    )
    state = run_event(graph, _session(), {"kind": "telemetry", "minute": 10})
    assert rec.calls == ["sentinel", "dispatcher"]
    assert state["alerts"] == [alert]


def test_session_is_shared_across_events():
    def sentinel(state):
        state["session"].memory["seen"] = state["session"].memory.get("seen", 0) + 1
        return {}

    graph = build_graph(sentinel=sentinel)
    session = _session()
    for minute in range(3):
        run_event(graph, session, {"kind": "telemetry", "minute": minute})
    assert session.memory["seen"] == 3


def test_unknown_event_kind_raises():
    with pytest.raises(ValueError, match="unknown shift event"):
        run_event(build_graph(), _session(), {"kind": "bogus"})
