"""Single-agent variant.

ReAct-style: the agent sees the task + tool list and chooses actions until
it emits a final answer or hits the per-run step budget. The same tool
contracts as the fixed graph (step 2) are used.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

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


def run_single_agent(adapter: LLMAdapter, task: str, *, max_steps: int = MAX_STEPS) -> SingleAgentOutput:
    """Single-agent loop. Stops on ANSWER/REFUSE/CLARIFY or budget exhaustion."""
    steps = 0
    transcript = [{"role": "user", "content": _REACT_PROMPT.format(task=task)}]
    while steps < max_steps:
        resp = adapter.chat(transcript)
        steps += 1
        text = (resp.content or "").strip()
        head = text.split(maxsplit=1)[0].upper() if text else ""
        if head == "ANSWER":
            return SingleAgentOutput(state=RunState.SUCCEEDED, answer=text[len("ANSWER "):].strip(), steps=steps)
        if head == "REFUSE":
            return SingleAgentOutput(state=RunState.SUCCEEDED, answer=_REFUSE_MESSAGE, steps=steps)
        if head == "CLARIFY":
            return SingleAgentOutput(state=RunState.SUCCEEDED, answer=_CLARIFY_MESSAGE, steps=steps)
        if head == "TOOL":
            # Tool dispatch is a stub for MVP; step 6 wires real MCP calls.
            transcript.append({"role": "assistant", "content": text})
            transcript.append({"role": "user", "content": "continue"})
            continue
        # Unknown head -> safe default: clarify
        return SingleAgentOutput(state=RunState.SUCCEEDED, answer=_CLARIFY_MESSAGE, steps=steps)
    # Budget exhausted
    return SingleAgentOutput(state=RunState.SUCCEEDED, answer=_REFUSE_MESSAGE, steps=steps)
