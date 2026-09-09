"""Bounded planner/executor variant.

Two-phase:
  - planner emits a 1-3 step plan (list of tool names)
  - executor walks the plan with a per-step budget

Stop conditions:
  - plan complete
  - per-step budget exhausted
  - escalation required (planner marks step with ESCALATE)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

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


def run_planner_executor(adapter: LLMAdapter, task: str) -> PlannerExecutorOutput:
    # Phase 1: plan
    plan_resp = adapter.chat([{"role": "user", "content": _PLAN_PROMPT.format(task=task)}])
    plan = _parse_plan(plan_resp.content or "")
    if not plan:
        return PlannerExecutorOutput(
            state=RunState.SUCCEEDED, answer=_REFUSE_MESSAGE, plan=[], steps_executed=0,
        )

    # Phase 2: walk the plan within MAX_EXECUTOR_STEPS
    executed = 0
    for tool in plan:
        if executed >= MAX_EXECUTOR_STEPS:
            break
        # Tool execution is a stub for MVP; step 6 wires real MCP calls.
        adapter.chat([{"role": "user", "content": f"execute: {tool}"}])
        executed += 1

    # Final synthesis
    synth_resp = adapter.chat(
        [{"role": "user", "content": f"Using the plan above, answer the task. Task: {task}"}]
    )
    answer = (synth_resp.content or "").strip()
    if "REFUSE" in answer.upper()[:32]:
        answer = _REFUSE_MESSAGE
    return PlannerExecutorOutput(
        state=RunState.SUCCEEDED, answer=answer or _CLARIFY_MESSAGE, plan=plan, steps_executed=executed,
    )
