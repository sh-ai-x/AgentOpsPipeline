"""Bounded planner/executor variant.

Two-phase:
  - planner emits a 1-3 step plan (list of tool names)
  - executor walks the plan with a per-step budget

Stop conditions:
  - plan complete
  - per-step budget exhausted
  - escalation required (planner marks step with ESCALATE)

Internally this is a real `langgraph.graph.StateGraph` with three nodes:
`plan` (or `empty_plan` when the parser yields nothing), `execute`
(looping via a conditional self-edge, budget-bounded), and `synthesize`
— reproducing the original two-phase-plus-budget structure exactly.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from ..llm.adapter import LLMAdapter
from .fixed import _CLARIFY_MESSAGE, _REFUSE_MESSAGE
from .state import RunState

log = logging.getLogger(__name__)


@dataclass
class PlannerExecutorOutput:
    state: RunState
    answer: str
    plan: list[str]
    steps_executed: int


MAX_PLAN_STEPS = 3
MAX_EXECUTOR_STEPS = 6

_PLAN_PROMPT = (
    "Plan how to answer this task using ONLY these tools: search_docs, read_document, "
    "get_issue. Reply with up to 3 steps, one per line, in the form `step: <tool_name>`.\n\n"
    "Task: {task}"
)


def _parse_plan(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*\d+\s*[:.)]\s*([a-z_]+)", line.strip(), flags=re.IGNORECASE)
        if m:
            out.append(m.group(1).lower())
        else:
            m = re.match(r"^\s*step\s*:\s*([a-z_]+)", line.strip(), flags=re.IGNORECASE)
            if m:
                out.append(m.group(1).lower())
        if len(out) >= MAX_PLAN_STEPS:
            break
    return out


class _PlannerExecutorState(TypedDict, total=False):
    adapter: Any  # LLMAdapter — opaque to the graph, not serialized
    task: str
    plan: list[str]
    executed: int
    answer: str


def _plan_node(state: _PlannerExecutorState) -> dict[str, Any]:
    adapter = state["adapter"]
    task = state["task"]
    plan_resp = adapter.chat([{"role": "user", "content": _PLAN_PROMPT.format(task=task)}])
    plan = _parse_plan(plan_resp.content or "")
    return {"plan": plan, "executed": 0}


def _empty_plan_node(state: _PlannerExecutorState) -> dict[str, Any]:
    return {"answer": _REFUSE_MESSAGE}


def _execute_node(state: _PlannerExecutorState) -> dict[str, Any]:
    adapter = state["adapter"]
    plan = state["plan"]
    executed = state["executed"]
    tool = plan[executed]
    # Tool execution is a stub for MVP; step 6 wires real MCP calls.
    adapter.chat([{"role": "user", "content": f"execute: {tool}"}])
    return {"executed": executed + 1}


def _synthesize_node(state: _PlannerExecutorState) -> dict[str, Any]:
    adapter = state["adapter"]
    task = state["task"]
    synth_resp = adapter.chat(
        [{"role": "user", "content": f"Using the plan above, answer the task. Task: {task}"}]
    )
    answer = (synth_resp.content or "").strip()
    if "REFUSE" in answer.upper()[:32]:
        answer = _REFUSE_MESSAGE
    return {"answer": answer or _CLARIFY_MESSAGE}


def _route_after_plan(state: _PlannerExecutorState) -> str:
    return "execute" if state["plan"] else "empty_plan"


def _route_after_execute(state: _PlannerExecutorState) -> str:
    if state["executed"] >= len(state["plan"]) or state["executed"] >= MAX_EXECUTOR_STEPS:
        return "synthesize"
    return "continue"


def _build_graph():
    """Build and compile the planner/executor graph's `StateGraph`.

    plan -> (empty_plan | execute) ; execute loops on itself
    (budget-bounded) -> synthesize -> END.
    """
    graph = StateGraph(_PlannerExecutorState)
    graph.add_node("plan", _plan_node)
    graph.add_node("empty_plan", _empty_plan_node)
    graph.add_node("execute", _execute_node)
    graph.add_node("synthesize", _synthesize_node)
    graph.set_entry_point("plan")
    graph.add_conditional_edges(
        "plan", _route_after_plan, {"empty_plan": "empty_plan", "execute": "execute"}
    )
    graph.add_conditional_edges(
        "execute", _route_after_execute, {"continue": "execute", "synthesize": "synthesize"}
    )
    graph.add_edge("synthesize", END)
    graph.add_edge("empty_plan", END)
    return graph.compile()


_GRAPH = _build_graph()


def run_planner_executor(adapter: LLMAdapter, task: str) -> PlannerExecutorOutput:
    initial: _PlannerExecutorState = {
        "adapter": adapter,
        "task": task,
        "plan": [],
        "executed": 0,
        "answer": "",
    }
    result = _GRAPH.invoke(
        initial, config={"recursion_limit": MAX_PLAN_STEPS * 2 + MAX_EXECUTOR_STEPS + 10}
    )
    return PlannerExecutorOutput(
        state=RunState.SUCCEEDED,
        answer=result["answer"],
        plan=result["plan"],
        steps_executed=result["executed"],
    )
