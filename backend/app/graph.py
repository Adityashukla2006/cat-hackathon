"""LangGraph orchestration: routes each shift event to the agent that handles it.

plan        -> planner
telemetry   -> sentinel -> dispatcher (only when the sentinel asks for a replan)
voice_note  -> scribe
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.state import GraphState, ShiftEvent, ShiftSession

Node = Callable[[GraphState], dict[str, Any]]

ROUTES = {"plan": "planner", "telemetry": "sentinel", "voice_note": "scribe"}


def _noop(state: GraphState) -> dict[str, Any]:
    return {}


def route_event(state: GraphState) -> str:
    kind = state["event"].get("kind")
    if kind not in ROUTES:
        raise ValueError(f"unknown shift event kind: {kind!r}")
    return ROUTES[kind]


def after_sentinel(state: GraphState) -> str:
    return "dispatcher" if state.get("needs_replan") else END


def build_graph(
    planner: Node = _noop,
    sentinel: Node = _noop,
    dispatcher: Node = _noop,
    scribe: Node = _noop,
):
    graph = StateGraph(GraphState)
    graph.add_node("planner", planner)
    graph.add_node("sentinel", sentinel)
    graph.add_node("dispatcher", dispatcher)
    graph.add_node("scribe", scribe)
    graph.add_conditional_edges(START, route_event, list(ROUTES.values()))
    graph.add_edge("planner", END)
    graph.add_conditional_edges("sentinel", after_sentinel, ["dispatcher", END])
    graph.add_edge("dispatcher", END)
    graph.add_edge("scribe", END)
    return graph.compile()


def run_event(graph: Any, session: ShiftSession, event: ShiftEvent) -> GraphState:
    """Run one event through the graph and return the final state."""
    return graph.invoke(
        {
            "session": session,
            "event": event,
            "alerts": [],
            "delta_min": None,
            "fatigue": None,
            "needs_replan": False,
            "replan_reason": None,
            "replan": None,
            "briefing": None,
            "incident": None,
            "transcript": None,
        }
    )


def default_graph():
    """The graph wired with the real agents."""
    from app.agents.dispatcher import dispatcher_node
    from app.agents.planner import planner_node
    from app.agents.scribe import scribe_node
    from app.agents.sentinel import sentinel_node

    return build_graph(
        planner=planner_node,
        sentinel=sentinel_node,
        dispatcher=dispatcher_node,
        scribe=scribe_node,
    )
