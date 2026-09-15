"""Fixed graph: retrieve -> classify -> (answer | refuse | clarify).

This is the MVP graph. Step 5 adds single-agent and planner/executor
variants using the same tool contracts.

Internally this is a real `langgraph.graph.StateGraph`: a `classify`
node decides the route, then conditional edges dispatch to `refuse`,
`clarify`, or `answer` terminal nodes — the same if/elif chain the
original plain-Python version encoded, now expressed as graph wiring.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

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
    "You are a triage classifier. Given the user task AND the retrieved docs "
    "below, respond with EXACTLY one of ANSWER, REFUSE, or CLARIFY on a single line.\n\n"
    "DECISION RULES (in priority order):\n"
    "  1. If the docs section says '(no relevant docs found)' -> REFUSE\n"
    "  2. If the task is gibberish or impossible -> REFUSE\n"
    "  3. Otherwise -> ANSWER (the docs are assumed sufficient; the answer step will quote them)\n\n"
    "Retrieved docs:\n{docs}\n\n"
    "Task: {task}\n"
)


def _classify(adapter: LLMAdapter, task: str, docs_dir: str = "fixtures/docs") -> str:
    """Return one of: answer, refuse, clarify.

    Deterministic by construction: the LLM is non-deterministic at
    temperature=0 (per uncertainty.md caveat), so we do NOT call the
    model here. Decision is based purely on retrieval: docs found ->
    ANSWER; no docs -> REFUSE. The answer step will quote whatever
    docs were retrieved.
    """
    docs = _retrieve_docs(task, docs_dir=docs_dir)
    if docs == "(no relevant docs found)":
        return "refuse"
    return "answer"


_ANSWER_PROMPT = (
    "You are a support agent. Use the retrieved docs below as your evidence.\n\n"
    "QUOTING RULES:\n"
    "  - Quote relevant passages from the docs verbatim.\n"
    "  - If the docs cover the topic (even partially), answer based on them.\n"
    "  - Only respond with the literal token REFUSE if the docs are completely unrelated to the task.\n"
    "  - Do NOT say REFUSE just because the docs are short.\n\n"
    "Retrieved docs:\n{docs}\n\n"
    "Task: {task}\n"
)


_STOPWORDS = frozenset({
    "the", "and", "with", "from", "for", "into", "this", "that",
    "are", "can", "you", "your", "how", "what", "when", "use",
    "have", "has", "had", "will", "would", "should", "could",
})


def _retrieve_docs(task: str, docs_dir: str = "fixtures/docs") -> str:
    """Lexical retrieval over the fixture corpus.

    Top-3 docs that match task tokens. Tokenization strips punctuation
    (so "PostgreSQL?" -> "postgresql"); common English stopwords are
    filtered; long tokens (>=7 chars) get a 6-char prefix fallback so
    stemmed variants still match ("postgresql" -> "postgres",
    "checkpointing" -> "checkpointers").
    """
    import re
    from pathlib import Path

    tokens = [
        t for t in re.findall(r"[a-z0-9]+", task.lower())
        if len(t) >= 3 and t not in _STOPWORDS
    ][:10]
    if not tokens:
        return "(no relevant docs found)"

    matches: list[tuple[str, int, str]] = []
    for f in sorted(Path(docs_dir).glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace").lower()
        hits = 0
        for t in tokens:
            if t in text:
                hits += 1
                continue
            # Prefix fallback for long tokens: "postgresql" -> "postgres",
            # "checkpointing" -> "checkpointers" / "checkpointer".
            if len(t) >= 7 and t[:6] in text:
                hits += 1
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


class _FixedGraphState(TypedDict, total=False):
    adapter: Any  # LLMAdapter — opaque to the graph, not serialized
    task: str
    docs_dir: str  # corpus directory; passed to _retrieve_docs
    route: str  # set by "classify"; consumed by the conditional edge
    answer: str | None
    rationale: str
    run_state: RunState


def _classify_node(state: _FixedGraphState) -> dict[str, Any]:
    route = _classify(state["adapter"], state["task"], state.get("docs_dir", "fixtures/docs"))
    log.info("fixed_graph: route=%s", route)
    return {"route": route}


def _refuse_node(state: _FixedGraphState) -> dict[str, Any]:
    return {
        "answer": _REFUSE_MESSAGE,
        "route": "refuse",
        "rationale": "no relevant evidence",
        "run_state": RunState.SUCCEEDED,
    }


def _clarify_node(state: _FixedGraphState) -> dict[str, Any]:
    return {
        "answer": _CLARIFY_MESSAGE,
        "route": "clarify",
        "rationale": "task is ambiguous",
        "run_state": RunState.SUCCEEDED,
    }


def _answer_node(state: _FixedGraphState) -> dict[str, Any]:
    task = state["task"]
    adapter = state["adapter"]
    retrieved = _retrieve_docs(task, state.get("docs_dir", "fixtures/docs"))
    prompt = _ANSWER_PROMPT.format(docs=retrieved, task=task)
    resp = adapter.chat([{"role": "user", "content": prompt}])
    content = (resp.content or "").strip()
    if "REFUSE" in content.upper()[:32]:
        return {
            "answer": _REFUSE_MESSAGE,
            "route": "refuse",
            "rationale": "answer model self-flagged REFUSE",
            "run_state": RunState.SUCCEEDED,
        }
    return {
        "answer": content,
        "route": "answer",
        "rationale": "answered from corpus",
        "run_state": RunState.SUCCEEDED,
    }


def _route_after_classify(state: _FixedGraphState) -> str:
    route = state["route"]
    if route == "refuse":
        return "refuse"
    if route == "clarify":
        return "clarify"
    return "answer"


def _build_graph():
    """Build and compile the fixed graph's `StateGraph`.

    classify -> (refuse | clarify | answer) -> END, reproducing the
    original if/elif chain as real conditional graph edges.
    """
    graph = StateGraph(_FixedGraphState)
    graph.add_node("classify", _classify_node)
    graph.add_node("refuse", _refuse_node)
    graph.add_node("clarify", _clarify_node)
    graph.add_node("answer", _answer_node)
    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"refuse": "refuse", "clarify": "clarify", "answer": "answer"},
    )
    graph.add_edge("refuse", END)
    graph.add_edge("clarify", END)
    graph.add_edge("answer", END)
    return graph.compile()


_GRAPH = _build_graph()


def run_fixed_graph(
    adapter: LLMAdapter, task: str, *, evidence: str = "", docs_dir: str = "fixtures/docs"
) -> GraphOutput:
    """Execute the fixed graph. Deterministic classify + answer."""
    log.info("fixed_graph: classify task len=%d corpus=%s", len(task), docs_dir)
    result = _GRAPH.invoke({"adapter": adapter, "task": task, "docs_dir": docs_dir})
    return GraphOutput(
        state=result["run_state"],
        answer=result["answer"],
        route=result["route"],
        rationale=result.get("rationale", ""),
    )


def bounded_steps_reached(steps: int, max_steps: int) -> bool:
    return steps >= max_steps
