"""Single-agent variant.

ReAct-style: the agent sees the task + tool list and chooses actions until
it emits a final answer or hits the per-run step budget. The same tool
contracts as the fixed graph (step 2) are used. TOOL dispatch calls a real
DocumentClient (search_docs / read_document); get_issue has no real backend
anywhere in this repo -- executing it normalises to
MCPError(kind="unsupported_capability") and the loop continues (see
docs/adr/0002-mcp-boundaries.md).

Internally this is a real `langgraph.graph.StateGraph`: a single
`agent_step` node loops on itself via a conditional edge (continue vs.
stop) until it emits a terminal answer or a separate `budget_exhausted`
node is reached, reproducing the original `while steps < max_steps` loop.

The tool-dispatch helpers below are intentionally NOT imported from
graph/planner_executor.py, which has the same shape (_execute_step /
_resolve_read_doc_id). Both modules were under active, independent PRs at
the same time -- importing across them would couple this module's merge
to that PR's, recreating the exact cross-PR merge-conflict class that the
StateGraph rewrite (PR #20) and tool-execution wiring (PR #21) already hit
on this same file. A future consolidation into a shared
graph/_tool_dispatch.py helper is reasonable once both have landed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from ..llm.adapter import LLMAdapter
from ..mcp import DocRef, DocumentClient, InMemoryDocumentClient, MCPError, classify_mcp_error
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
    tool_results: list[dict]


MAX_STEPS = 8

# Snippet length folded into the tool-result message fed back to the LLM
# after a read_document call. Generous enough to carry a real passage,
# bounded so the transcript stays small across many loop iterations.
_CONTEXT_SNIPPET_CHARS = 800


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


def _resolve_read_doc_id(
    task: str, last_search_results: list[DocRef], client: DocumentClient
) -> tuple[str | None, list[DocRef]]:
    """doc_id to read: the top-ranked prior search_docs hit, or -- when no
    search_docs step has run yet -- a fresh search over the task text.

    Returns (doc_id, updated last_search_results) so a fallback search's
    hits get cached, same as a real search_docs step would -- otherwise
    two read_document calls with no preceding search_docs would re-run the
    identical fallback search twice.
    """
    if last_search_results:
        return last_search_results[0].doc_id, last_search_results
    fallback = client.search_docs(task, top_k=1)
    if fallback:
        return fallback[0].doc_id, fallback
    return None, last_search_results


def _execute_tool(
    tool: str,
    task: str,
    client: DocumentClient,
    last_search_results: list[DocRef],
) -> tuple[str, str | None, list[DocRef], dict[str, Any], str | None]:
    """Run one TOOL directive against the real DocumentClient.

    Returns (outcome, error_kind, updated last_search_results, args_used,
    retrieved_snippet). `args_used` is the real argument the tool was
    actually invoked with -- callers persist this as the real ToolCall
    args, not a placeholder. `retrieved_snippet` is the read_document text
    (if any), for the caller to fold into the transcript. Never raises --
    every failure is normalised via classify_mcp_error and reported
    through the return value so the loop can continue.
    """
    args: dict[str, Any] = {}
    snippet: str | None = None
    try:
        if tool == "search_docs":
            args = {"query": task}
            last_search_results = client.search_docs(task)
        elif tool == "read_document":
            doc_id, last_search_results = _resolve_read_doc_id(task, last_search_results, client)
            if doc_id is None:
                raise ValueError("read_document: no candidate doc_id (search returned no hits)")
            args = {"doc_id": doc_id}
            snippet = client.read_document(doc_id)[:_CONTEXT_SNIPPET_CHARS]
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
            raise ValueError(f"unknown tool in TOOL directive: {tool!r}")
    except Exception as exc:  # noqa: BLE001 - normalised via classify_mcp_error
        mcp_err = exc if isinstance(exc, MCPError) else classify_mcp_error(exc)
        log.info("single_agent: tool=%s failed kind=%s", tool, mcp_err.kind)
        return "error", mcp_err.kind, last_search_results, args, None
    return "ok", None, last_search_results, args, snippet


def _tool_result_message(
    tool: str,
    outcome: str,
    error_kind: str | None,
    last_search_results: list[DocRef],
    snippet: str | None,
) -> str:
    """Message fed back to the LLM after a TOOL call -- ReAct-style, so it
    is folded into the next turn's transcript rather than a deferred final
    synthesis prompt."""
    if outcome == "error":
        return f"TOOL_RESULT {tool}: error ({error_kind})"
    if tool == "search_docs":
        if not last_search_results:
            return "TOOL_RESULT search_docs: no matching documents"
        ids = ", ".join(r.doc_id for r in last_search_results[:5])
        return f"TOOL_RESULT search_docs: found {ids}"
    if tool == "read_document" and snippet is not None:
        doc_id = last_search_results[0].doc_id if last_search_results else "?"
        return f"TOOL_RESULT read_document [{doc_id}]: {snippet}"
    return f"TOOL_RESULT {tool}: ok"


class _SingleAgentState(TypedDict, total=False):
    adapter: Any  # LLMAdapter — opaque to the graph, not serialized
    document_client: Any  # DocumentClient — opaque to the graph, not serialized
    task: str
    transcript: list[dict[str, str]]
    steps: int
    max_steps: int
    done: bool
    answer: str
    tool_results: list[dict]
    last_search_results: list[DocRef]


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
        parts = text.split(maxsplit=2)
        tool = parts[1].lower() if len(parts) >= 2 else ""
        if not tool:
            # Malformed directive, no tool name -- same safe default as
            # any other unparseable head.
            return {"steps": steps, "done": True, "answer": _CLARIFY_MESSAGE}
        client: DocumentClient = state["document_client"]
        last_search_results = state.get("last_search_results", [])
        tool_results = list(state.get("tool_results", []))

        start = time.monotonic()
        outcome, error_kind, last_search_results, args, snippet = _execute_tool(
            tool, state["task"], client, last_search_results
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
        result_msg = _tool_result_message(tool, outcome, error_kind, last_search_results, snippet)
        new_transcript = transcript + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": result_msg},
        ]
        return {
            "steps": steps,
            "transcript": new_transcript,
            "done": False,
            "tool_results": tool_results,
            "last_search_results": last_search_results,
        }
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


def run_single_agent(
    adapter: LLMAdapter,
    task: str,
    *,
    max_steps: int = MAX_STEPS,
    document_client: DocumentClient | None = None,
    corpus_dir: str = "fixtures/docs",
) -> SingleAgentOutput:
    """Single-agent loop. Stops on ANSWER/REFUSE/CLARIFY or budget exhaustion."""
    if document_client is None:
        if corpus_dir and corpus_dir != "fixtures/docs":
            from ..adapters.wiki_rag import WikiRagAdapter

            document_client = WikiRagAdapter(corpus_dir)
        else:
            document_client = InMemoryDocumentClient()
    client: DocumentClient = document_client
    initial: _SingleAgentState = {
        "adapter": adapter,
        "document_client": client,
        "task": task,
        "transcript": [{"role": "user", "content": _REACT_PROMPT.format(task=task)}],
        "steps": 0,
        "max_steps": max_steps,
        "done": False,
        "answer": "",
        "tool_results": [],
        "last_search_results": [],
    }
    result = _GRAPH.invoke(initial, config={"recursion_limit": max_steps * 2 + 10})
    return SingleAgentOutput(
        state=RunState.SUCCEEDED,
        answer=result["answer"],
        steps=result["steps"],
        tool_results=result.get("tool_results", []),
    )
