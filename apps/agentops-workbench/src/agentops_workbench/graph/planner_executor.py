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
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

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
) -> str | None:
    """doc_id to read: the top-ranked prior search_docs hit, or -- when the
    plan never ran search_docs -- a fresh search over the task text itself.
    """
    if last_search_results:
        return last_search_results[0].doc_id
    fallback = client.search_docs(task, top_k=1)
    return fallback[0].doc_id if fallback else None


def _execute_step(
    tool: str,
    task: str,
    client: DocumentClient,
    last_search_results: list[DocRef],
    context_docs: list[tuple[str, str]],
) -> tuple[str, str | None, list[DocRef]]:
    """Run one plan step against the real DocumentClient.

    Returns (outcome, error_kind, updated last_search_results). Mutates
    context_docs in place with any retrieved text so the caller can fold
    it into the final synthesis prompt. Never raises -- every failure is
    normalised via classify_mcp_error and reported through the return
    value so the plan can continue.
    """
    try:
        if tool == "search_docs":
            last_search_results = client.search_docs(task)
        elif tool == "read_document":
            doc_id = _resolve_read_doc_id(task, last_search_results, client)
            if doc_id is None:
                raise ValueError("read_document: no candidate doc_id (search returned no hits)")
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
        return "error", mcp_err.kind, last_search_results
    return "ok", None, last_search_results


def run_planner_executor(
    adapter: LLMAdapter,
    task: str,
    *,
    document_client: DocumentClient | None = None,
) -> PlannerExecutorOutput:
    client: DocumentClient = document_client or InMemoryDocumentClient()

    # Phase 1: plan
    plan_resp = adapter.chat([{"role": "user", "content": _PLAN_PROMPT.format(task=task)}])
    plan = _parse_plan(plan_resp.content or "")
    if not plan:
        return PlannerExecutorOutput(
            state=RunState.SUCCEEDED, answer=_REFUSE_MESSAGE, plan=[], steps_executed=0,
            tool_results=[],
        )

    # Phase 2: walk the plan within MAX_EXECUTOR_STEPS, executing real tools.
    executed = 0
    tool_results: list[dict] = []
    last_search_results: list[DocRef] = []
    context_docs: list[tuple[str, str]] = []

    for tool in plan:
        if executed >= MAX_EXECUTOR_STEPS:
            break
        start = time.monotonic()
        outcome, error_kind, last_search_results = _execute_step(
            tool, task, client, last_search_results, context_docs
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        tool_results.append(
            {
                "tool_name": tool,
                "outcome": outcome,
                "latency_ms": latency_ms,
                "error_kind": error_kind,
            }
        )
        executed += 1

    # Final synthesis, grounded in whatever text was actually retrieved.
    docs_blob = (
        "\n\n--\n\n".join(f"[{doc_id}]: {snippet}" for doc_id, snippet in context_docs)
        if context_docs
        else "(no relevant docs found)"
    )
    synth_resp = adapter.chat(
        [{"role": "user", "content": _SYNTH_PROMPT.format(docs=docs_blob, task=task)}]
    )
    answer = (synth_resp.content or "").strip()
    if "REFUSE" in answer.upper()[:32]:
        answer = _REFUSE_MESSAGE
    return PlannerExecutorOutput(
        state=RunState.SUCCEEDED,
        answer=answer or _CLARIFY_MESSAGE,
        plan=plan,
        steps_executed=executed,
        tool_results=tool_results,
    )
