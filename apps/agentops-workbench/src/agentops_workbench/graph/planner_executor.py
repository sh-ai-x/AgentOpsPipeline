"""Bounded planner/executor variant.

Two-phase:
  - planner emits a 1-3 step plan (list of tool names)
  - executor walks the plan with a per-step budget, dispatching each
    step to a real DocumentClient call (search_docs / read_document).
    get_issue has no real backend anywhere in this repo -- executing it
    normalises to MCPError(kind="unsupported_capability") and the plan
    continues (see docs/adr/0002-mcp-boundaries.md).

Stop conditions:
  - plan complete
  - per-step budget exhausted
  - escalation required (planner marks step with ESCALATE)

Internally this is a real `langgraph.graph.StateGraph` with three nodes:
`plan` (or `empty_plan` when the parser yields nothing), `execute`
(looping via a conditional self-edge, budget-bounded), and `synthesize`
— reproducing the original two-phase-plus-budget structure exactly, with
the real tool execution living inside the `execute` node's per-step logic.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from ..llm.adapter import LLMAdapter
from ..mcp import DocRef, DocumentClient, InMemoryDocumentClient, MCPError, classify_mcp_error
from .fixed import _CLARIFY_MESSAGE, _REFUSE_MESSAGE
from .state import RunState

log = logging.getLogger(__name__)


@dataclass
class PlannerExecutorOutput:
    state: RunState
    answer: str
    plan: list[str]
    steps_executed: int
    tool_results: list[dict]


MAX_PLAN_STEPS = 3
MAX_EXECUTOR_STEPS = 6

# Snippet length folded into the final synthesis prompt per read_document
# call. Generous enough to carry a real passage, bounded so the prompt
# stays small.
_CONTEXT_SNIPPET_CHARS = 800

_PLAN_PROMPT = (
    "Plan how to answer this task using ONLY these tools: search_docs, read_document, "
    "get_issue. Reply with up to 3 steps, one per line, in the form `step: <tool_name>`.\n\n"
    "Task: {task}"
)

_SYNTH_PROMPT = (
    "Using the plan and retrieved evidence below, answer the task.\n\n"
    "Retrieved docs:\n{docs}\n\nTask: {task}\n"
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


def _resolve_read_doc_id(
    task: str, last_search_results: list[DocRef], client: DocumentClient
) -> tuple[str | None, list[DocRef]]:
    """doc_id to read: the top-ranked prior search_docs hit, or -- when the
    plan never ran search_docs -- a fresh search over the task text itself.

    Returns (doc_id, updated last_search_results) so a fallback search's
    hits get cached the same way a real search_docs step's would --
    otherwise a plan with two read_document steps and no search_docs step
    would re-run the identical fallback search twice.
    """
    if last_search_results:
        return last_search_results[0].doc_id, last_search_results
    fallback = client.search_docs(task, top_k=1)
    if fallback:
        return fallback[0].doc_id, fallback
    return None, last_search_results


def _execute_step(
    tool: str,
    task: str,
    client: DocumentClient,
    last_search_results: list[DocRef],
    context_docs: list[tuple[str, str]],
) -> tuple[str, str | None, list[DocRef], dict[str, Any]]:
    """Run one plan step against the real DocumentClient.

    Returns (outcome, error_kind, updated last_search_results, args_used).
    `args_used` is the real argument the tool was actually invoked with
    (`{"query": task}` for search_docs, `{"doc_id": doc_id}` for
    read_document, `{}` otherwise) -- callers persist this as the real
    ToolCall args instead of a fabricated placeholder, so the crash-recovery
    idempotency invariant (graph/state.py:make_action_key) is keyed on what
    actually happened, not on step position. Mutates context_docs in place
    with any retrieved text so the caller can fold it into the final
    synthesis prompt. Never raises -- every failure is normalised via
    classify_mcp_error and reported through the return value so the plan
    can continue.
    """
    args: dict[str, Any] = {}
    try:
        if tool == "search_docs":
            args = {"query": task}
            last_search_results = client.search_docs(task)
        elif tool == "read_document":
            doc_id, last_search_results = _resolve_read_doc_id(task, last_search_results, client)
            if doc_id is None:
                raise ValueError("read_document: no candidate doc_id (search returned no hits)")
            args = {"doc_id": doc_id}
            text = client.read_document(doc_id)
            context_docs.append((doc_id, text[:_CONTEXT_SNIPPET_CHARS]))
        elif tool == "get_issue":
            # No real issue tracker backend exists anywhere in this repo
            # (fixtures/cases/schema.json allows the tool name, but there
            # is no mock or MCP server behind it). Normalise honestly
            # instead of inventing fake issue data.
            raise NotImplementedError(
                "get_issue is not supported: no issue tracker backend is "
                "configured in this environment"
            )
        else:
            raise ValueError(f"unknown tool in plan: {tool!r}")
    except Exception as exc:  # noqa: BLE001 - normalised via classify_mcp_error
        mcp_err = exc if isinstance(exc, MCPError) else classify_mcp_error(exc)
        log.info("planner_executor: tool=%s failed kind=%s", tool, mcp_err.kind)
        return "error", mcp_err.kind, last_search_results, args
    return "ok", None, last_search_results, args


class _PlannerExecutorState(TypedDict, total=False):
    adapter: Any  # LLMAdapter — opaque to the graph, not serialized
    document_client: Any  # DocumentClient — opaque to the graph, not serialized
    task: str
    plan: list[str]
    executed: int
    answer: str
    tool_results: list[dict]
    last_search_results: list[DocRef]
    context_docs: list[tuple[str, str]]


def _plan_node(state: _PlannerExecutorState) -> dict[str, Any]:
    adapter = state["adapter"]
    task = state["task"]
    plan_resp = adapter.chat([{"role": "user", "content": _PLAN_PROMPT.format(task=task)}])
    plan = _parse_plan(plan_resp.content or "")
    return {"plan": plan, "executed": 0}


def _empty_plan_node(state: _PlannerExecutorState) -> dict[str, Any]:
    return {"answer": _REFUSE_MESSAGE}


def _execute_node(state: _PlannerExecutorState) -> dict[str, Any]:
    """Dispatch one plan step against the real DocumentClient.

    Runs `_execute_step` (search_docs / read_document / get_issue) and
    accumulates the result into `tool_results`, `last_search_results`, and
    `context_docs` so the loop's later iterations and the final
    `synthesize` node see everything retrieved so far.
    """
    task = state["task"]
    client: DocumentClient = state["document_client"]
    plan = state["plan"]
    executed = state["executed"]
    tool = plan[executed]
    last_search_results = state.get("last_search_results", [])
    context_docs = list(state.get("context_docs", []))
    tool_results = list(state.get("tool_results", []))

    start = time.monotonic()
    outcome, error_kind, last_search_results, args = _execute_step(
        tool, task, client, last_search_results, context_docs
    )
    latency_ms = int((time.monotonic() - start) * 1000)
    tool_results.append(
        {
            "tool_name": tool,
            "outcome": outcome,
            "latency_ms": latency_ms,
            "error_kind": error_kind,
            "args": args,
        }
    )
    return {
        "executed": executed + 1,
        "tool_results": tool_results,
        "last_search_results": last_search_results,
        "context_docs": context_docs,
    }


def _synthesize_node(state: _PlannerExecutorState) -> dict[str, Any]:
    """Fold everything retrieved so far into the final prompt.

    `context_docs` (populated only by read_document) takes priority since
    it carries real passage text. A plan consisting of search_docs alone --
    a plausible single-step plan -- never touches context_docs, so without
    this fallback its hits would be silently discarded and the answer
    synthesized ungrounded despite search_docs having found real matches.
    """
    adapter = state["adapter"]
    task = state["task"]
    context_docs = state.get("context_docs", [])
    last_search_results = state.get("last_search_results", [])
    if context_docs:
        docs_blob = "\n\n--\n\n".join(f"[{doc_id}]: {snippet}" for doc_id, snippet in context_docs)
    elif last_search_results:
        ids = ", ".join(r.doc_id for r in last_search_results)
        docs_blob = f"(search_docs found candidate documents but none were read in full: {ids})"
    else:
        docs_blob = "(no relevant docs found)"
    synth_resp = adapter.chat(
        [{"role": "user", "content": _SYNTH_PROMPT.format(docs=docs_blob, task=task)}]
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
    (budget-bounded), dispatching a real DocumentClient tool call each
    iteration, -> synthesize -> END.
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


def run_planner_executor(
    adapter: LLMAdapter,
    task: str,
    *,
    document_client: DocumentClient | None = None,
) -> PlannerExecutorOutput:
    client: DocumentClient = document_client or InMemoryDocumentClient()
    initial: _PlannerExecutorState = {
        "adapter": adapter,
        "document_client": client,
        "task": task,
        "plan": [],
        "executed": 0,
        "answer": "",
        "tool_results": [],
        "last_search_results": [],
        "context_docs": [],
    }
    result = _GRAPH.invoke(
        initial, config={"recursion_limit": MAX_PLAN_STEPS * 2 + MAX_EXECUTOR_STEPS + 10}
    )
    return PlannerExecutorOutput(
        state=RunState.SUCCEEDED,
        answer=result["answer"],
        plan=result["plan"],
        steps_executed=result["executed"],
        tool_results=result.get("tool_results", []),
    )
