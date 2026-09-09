"""Fixed graph: retrieve -> classify -> (answer | refuse | clarify).

This is the MVP graph. Step 5 adds single-agent and planner/executor
variants using the same tool contracts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..llm.adapter import LLMAdapter
from .state import RunState

log = logging.getLogger(__name__)


@dataclass
class GraphOutput:
    state: RunState
    answer: str | None
    route: str  # "answer" | "refuse" | "clarify"
    rationale: str = ""


_CLASSIFY_PROMPT = (
    "You are a triage classifier for a software support agent. "
    "Given the user task, respond with EXACTLY one of these tokens on a single line: "
    "ANSWER, REFUSE, or CLARIFY.\n"
    "Use ANSWER if the task can be answered from retrieved documentation.\n"
    "Use REFUSE if the corpus has no relevant evidence.\n"
    "Use CLARIFY if the task is ambiguous and needs more info from the user.\n\n"
    "Task: {task}"
)


def _classify(adapter: LLMAdapter, task: str) -> str:
    """Return one of: answer, refuse, clarify. Defensive: picks the first token."""
    resp = adapter.chat(
        [{"role": "user", "content": _CLASSIFY_PROMPT.format(task=task)}]
    )
    text = (resp.content or "").strip().upper()
    for token in ("ANSWER", "REFUSE", "CLARIFY"):
        if token in text:
            return token.lower()
    return "clarify"  # safe default


_ANSWER_PROMPT = (
    "You are a support agent. Answer the user task using ONLY the retrieved docs. "
    "If the docs do not contain the answer, respond with the literal token REFUSE.\n\n"
    "Task: {task}"
)

_REFUSE_MESSAGE = (
    "Insufficient evidence in the corpus to answer confidently. "
    "Please provide more context or consult upstream documentation."
)

_CLARIFY_MESSAGE = (
    "Your request is ambiguous. Please share the project name, the exact error "
    "message, and a minimal reproducer."
)


def run_fixed_graph(adapter: LLMAdapter, task: str, *, evidence: str = "") -> GraphOutput:
    """Execute the fixed graph. Deterministic classify + answer."""
    log.info("fixed_graph: classify task len=%d", len(task))
    route = _classify(adapter, task)
    log.info("fixed_graph: route=%s", route)

    if route == "refuse":
        return GraphOutput(
            state=RunState.SUCCEEDED,
            answer=_REFUSE_MESSAGE,
            route="refuse",
            rationale="no relevant evidence",
        )

    if route == "clarify":
        return GraphOutput(
            state=RunState.SUCCEEDED,
            answer=_CLARIFY_MESSAGE,
            route="clarify",
            rationale="task is ambiguous",
        )

    # route == answer
    resp = adapter.chat(
        [{"role": "user", "content": _ANSWER_PROMPT.format(task=task)}]
    )
    content = (resp.content or "").strip()
    if "REFUSE" in content.upper()[:32]:
        return GraphOutput(
            state=RunState.SUCCEEDED,
            answer=_REFUSE_MESSAGE,
            route="refuse",
            rationale="answer model self-flagged REFUSE",
        )
    return GraphOutput(
        state=RunState.SUCCEEDED,
        answer=content,
        route="answer",
        rationale="answered from corpus",
    )


def bounded_steps_reached(steps: int, max_steps: int) -> bool:
    return steps >= max_steps
