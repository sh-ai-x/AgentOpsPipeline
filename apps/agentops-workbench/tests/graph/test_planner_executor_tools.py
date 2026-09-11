"""TDD regression — real MCP tool execution in the planner/executor graph.

Coverage:
  - search_docs / read_document wiring: real DocumentClient calls, injectable
    via `document_client=`, retrieved text folded into the final synthesis
    prompt so the answer is grounded.
  - get_issue: no real backend anywhere in this repo. Executing it must
    normalise to MCPError(kind="unsupported_capability"), record that as a
    failed tool_results entry, and NOT crash the run or halt the plan.
  - PlannerExecutorOutput.tool_results: one {tool_name, outcome, latency_ms,
    error_kind} dict per executed step.
"""
from __future__ import annotations

from typing import Any

from agentops_workbench.graph.planner_executor import run_planner_executor
from agentops_workbench.graph.state import RunState
from agentops_workbench.llm.adapter import ChatResult, LLMAdapter, Usage
from agentops_workbench.mcp import DocRef


class _ScriptedAdapter(LLMAdapter):
    """Minimal LLMAdapter test double: returns queued responses in order and
    records every prompt it was called with so tests can assert on grounding.
    """

    provider = "scripted-test"
    model = "scripted-v1"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []
        self._last_usage: Usage | None = None

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kw: Any,
    ) -> ChatResult:
        self.calls.append(messages)
        content = self._responses.pop(0) if self._responses else ""
        usage = Usage(
            provider=self.provider,
            model=self.model,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            cost_usd=0.0,
        )
        self._last_usage = usage
        return ChatResult(content=content, usage=usage)


class _StubDocumentClient:
    """Fake DocumentClient for the injectability test."""

    def search_docs(self, query: str, top_k: int = 5) -> list[DocRef]:
        return [DocRef(doc_id="stub-doc", title="stub", score=1.0)]

    def read_document(self, doc_id: str, offset: int = 0, limit: int = 2000) -> str:
        return "stub content unique-marker-xyz"

    def list_filesystem_files(self) -> list[str]:
        return []


# ---- search_docs / read_document wiring ----


def test_planner_executor_executes_search_docs_and_read_document() -> None:
    adapter = _ScriptedAdapter(
        ["step: search_docs\nstep: read_document", "ANSWER: grounded"]
    )
    out = run_planner_executor(adapter, "Explain PostgresCheckpointer persistence in LangGraph")
    assert out.plan == ["search_docs", "read_document"]
    assert out.steps_executed == 2
    assert len(out.tool_results) == 2
    assert out.tool_results[0]["tool_name"] == "search_docs"
    assert out.tool_results[0]["outcome"] == "ok"
    assert out.tool_results[0]["error_kind"] is None
    assert out.tool_results[1]["tool_name"] == "read_document"
    assert out.tool_results[1]["outcome"] == "ok"
    assert out.tool_results[1]["error_kind"] is None


def test_planner_executor_grounds_final_prompt_in_retrieved_document_text() -> None:
    adapter = _ScriptedAdapter(
        ["step: search_docs\nstep: read_document", "ANSWER: grounded"]
    )
    run_planner_executor(adapter, "Explain PostgresCheckpointer persistence in LangGraph")
    assert len(adapter.calls) == 2
    final_prompt = adapter.calls[1][0]["content"]
    # doc-001-langgraph-persistence.md is the only fixture doc mentioning
    # PostgresCheckpointer literally -- if this text is in the final
    # synthesis prompt, the retrieved doc content was actually folded in.
    assert "PostgresCheckpointer" in final_prompt


def test_planner_executor_read_document_uses_task_text_when_search_not_planned() -> None:
    """No search_docs step planned -> read_document must still resolve a
    doc_id, falling back to searching the task text itself."""
    adapter = _ScriptedAdapter(["step: read_document", "ANSWER: grounded"])
    out = run_planner_executor(adapter, "Explain PostgresCheckpointer persistence in LangGraph")
    assert out.tool_results[0]["tool_name"] == "read_document"
    assert out.tool_results[0]["outcome"] == "ok"
    final_prompt = adapter.calls[1][0]["content"]
    assert "PostgresCheckpointer" in final_prompt


def test_document_client_is_injectable() -> None:
    adapter = _ScriptedAdapter(["step: search_docs\nstep: read_document", "ANSWER: grounded"])
    out = run_planner_executor(
        adapter, "anything", document_client=_StubDocumentClient()
    )
    assert out.tool_results[0]["outcome"] == "ok"
    assert out.tool_results[1]["outcome"] == "ok"
    final_prompt = adapter.calls[1][0]["content"]
    assert "unique-marker-xyz" in final_prompt


# ---- get_issue: no real backend, must not crash ----


def test_planner_executor_get_issue_records_unsupported_capability() -> None:
    adapter = _ScriptedAdapter(["step: get_issue", "ANSWER: no issue backend"])
    out = run_planner_executor(adapter, "look up issue ABC-123")
    assert out.state == RunState.SUCCEEDED  # does not crash the run
    assert out.steps_executed == 1
    assert out.tool_results[0]["tool_name"] == "get_issue"
    assert out.tool_results[0]["outcome"] == "error"
    assert out.tool_results[0]["error_kind"] == "unsupported_capability"


def test_planner_executor_get_issue_does_not_halt_the_plan() -> None:
    adapter = _ScriptedAdapter(["step: get_issue\nstep: search_docs", "ANSWER: mixed"])
    out = run_planner_executor(adapter, "issue ABC-123 and also PostgresCheckpointer")
    assert out.steps_executed == 2
    assert out.tool_results[0]["outcome"] == "error"
    assert out.tool_results[0]["error_kind"] == "unsupported_capability"
    assert out.tool_results[1]["tool_name"] == "search_docs"
    assert out.tool_results[1]["outcome"] == "ok"
