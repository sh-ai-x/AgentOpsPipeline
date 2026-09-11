"""Single-agent variant.

ReAct-style: the agent sees the task + tool list and chooses actions until
it emits a final answer or hits the per-run step budget. The same tool
contracts as the fixed graph (step 2) are used.

Internally this is a real `langgraph.graph.StateGraph`: a single
`agent_step` node loops on itself via a conditional edge (continue vs.
stop) until it emits a terminal answer or a separate `budget_exhausted`
node is reached, reproducing the original `while steps < max_steps` loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from ..llm.adapter import LLMAdapter
from .fixed import (
    _CLARIFY_MESSAGE,
    _REFUSE_MESSAGE,
)
from .state import RunState

log = logging.getLogger(__name__)


@dataclass
class SingleAgentOutput:
    state: RunState
    answer: str
    steps: int


MAX_STEPS = 8


_REACT_PROMPT = (
    "You are a support agent. The user task is below. Tools available: search_docs, "
    "read_document, get_issue.\n\n"
    "Respond with EXACTLY one of:\n"
    "  ANSWER <text>\n"
    "  REFUSE\n"
    "  CLARIFY <text>\n"
    "  TOOL <tool_name> <json_args>\n\n"
    "Task: {task}"
)


class _SingleAgentState(TypedDict, total=False):
    adapter: Any  # LLMAdapter — opaque to the graph, not serialized
    task: str
    transcript: list[dict[str, str]]
    steps: int
    max_steps: int
    done: bool
    answer: str


def _agent_step_node(state: _SingleAgentState) -> dict[str, Any]:
    adapter = state["adapter"]
    transcript = state["transcript"]
    resp = adapter.chat(transcript)
    steps = state["steps"] + 1
    text = (resp.content or "").strip()
    head = text.split(maxsplit=1)[0].upper() if text else ""

    if head == "ANSWER":
        return {"steps": steps, "done": True, "answer": text[len("ANSWER "):].strip()}
    if head == "REFUSE":
        return {"steps": steps, "done": True, "answer": _REFUSE_MESSAGE}
    if head == "CLARIFY":
        return {"steps": steps, "done": True, "answer": _CLARIFY_MESSAGE}
    if head == "TOOL":
        # Tool dispatch is a stub for MVP; step 6 wires real MCP calls.
        new_transcript = transcript + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "continue"},
        ]
        return {"steps": steps, "transcript": new_transcript, "done": False}
    # Unknown head -> safe default: clarify
    return {"steps": steps, "done": True, "answer": _CLARIFY_MESSAGE}


def _budget_exhausted_node(state: _SingleAgentState) -> dict[str, Any]:
    return {"answer": _REFUSE_MESSAGE, "done": True}


def _route_after_step(state: _SingleAgentState) -> str:
    if state["done"]:
        return "stop"
    if state["steps"] >= state["max_steps"]:
        return "budget_exhausted"
    return "continue"


def _build_graph():
    """Build and compile the single-agent graph's `StateGraph`.

    `agent_step` conditionally loops back to itself (continue), stops at
    END on a terminal ANSWER/REFUSE/CLARIFY/unknown-head, or routes to
    `budget_exhausted` once the step budget runs out — the same
    `while steps < max_steps` semantics as the original loop.
    """
    graph = StateGraph(_SingleAgentState)
    graph.add_node("agent_step", _agent_step_node)
    graph.add_node("budget_exhausted", _budget_exhausted_node)
    graph.set_entry_point("agent_step")
    graph.add_conditional_edges(
        "agent_step",
        _route_after_step,
        {"stop": END, "continue": "agent_step", "budget_exhausted": "budget_exhausted"},
    )
    graph.add_edge("budget_exhausted", END)
    return graph.compile()


_GRAPH = _build_graph()


def run_single_agent(adapter: LLMAdapter, task: str, *, max_steps: int = MAX_STEPS) -> SingleAgentOutput:
    """Single-agent loop. Stops on ANSWER/REFUSE/CLARIFY or budget exhaustion."""
    initial: _SingleAgentState = {
        "adapter": adapter,
        "task": task,
        "transcript": [{"role": "user", "content": _REACT_PROMPT.format(task=task)}],
        "steps": 0,
        "max_steps": max_steps,
        "done": False,
        "answer": "",
    }
    result = _GRAPH.invoke(initial, config={"recursion_limit": max_steps * 2 + 10})
    return SingleAgentOutput(state=RunState.SUCCEEDED, answer=result["answer"], steps=result["steps"])
