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
    "Given the user task AND the retrieved docs, respond with EXACTLY one of "
    "ANSWER, REFUSE, or CLARIFY on a single line.\n"
    "Use ANSWER if the docs contain enough evidence.\n"
    "Use REFUSE if the docs have no relevant evidence.\n"
    "Use CLARIFY if the task is too ambiguous to answer even with the docs.\n\n"
    "Retrieved docs:\n{docs}\n\n"
    "Task: {task}"
)


def _classify(adapter: LLMAdapter, task: str) -> str:
    """Return one of: answer, refuse, clarify. Defensive: picks the first token."""
    docs = _retrieve_docs(task)
    resp = adapter.chat(
        [{"role": "user", "content": _CLASSIFY_PROMPT.format(docs=docs, task=task)}]
    )
    text = (resp.content or "").strip().upper()
    for token in ("ANSWER", "REFUSE", "CLARIFY"):
        if token in text:
            return token.lower()
    return "clarify"  # safe default


_ANSWER_PROMPT = (
    "You are a support agent. Answer the user task using ONLY the retrieved docs "
    "below. If the docs do not contain the answer, respond with the literal token REFUSE.\n\n"
    "Retrieved docs:\n{docs}\n\n"
    "Task: {task}"
)


def _retrieve_docs(task: str, docs_dir: str = "fixtures/docs") -> str:
    """Lexical retrieval over the fixture corpus. Top-3 docs that match task tokens."""
    from pathlib import Path
    tokens = [t.lower() for t in task.split() if len(t) >= 3][:10]
    if not tokens:
        return "(no relevant docs found)"
    matches: list[tuple[str, int, str]] = []
    for f in sorted(Path(docs_dir).glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        hits = sum(text.lower().count(t) for t in tokens)
        if hits > 0:
            matches.append((f.stem, hits, text[:500]))
    matches.sort(key=lambda m: -m[1])
    if not matches:
        return "(no relevant docs found)"
    return "\n\n--\n\n".join(f"[{stem}]: {snippet}" for stem, _, snippet in matches[:3])

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
    retrieved = _retrieve_docs(task)
    prompt = _ANSWER_PROMPT.format(docs=retrieved, task=task)
    resp = adapter.chat(
        [{"role": "user", "content": prompt}]
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
