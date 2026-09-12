"""TDD regression — real MCP tool execution in the single-agent (ReAct) graph.

Mirrors tests/graph/test_planner_executor_tools.py's coverage, adapted to
single_agent's TOOL <tool_name> <json_args> directive and ReAct-style
interleaved loop (each tool result is fed back into the transcript for the
next LLM turn, rather than folded into one final synthesis prompt):

  - search_docs / read_document: real DocumentClient calls, injectable via
    `document_client=`, the tool result summary fed back into the transcript
    so the next turn is actually grounded.
  - get_issue: no real backend anywhere in this repo. Executing it must
    normalise to MCPError(kind="unsupported_capability"), record that as a
    failed tool_results entry, and NOT crash the run or halt the loop.
  - A malformed `TOOL` directive with no tool name must not crash — it falls
    back to CLARIFY, same as any other unparseable head.
  - SingleAgentOutput.tool_results: one {tool_name, outcome, latency_ms,
    error_kind} dict per executed TOOL step.
"""
from __future__ import annotations

from typing import Any

from agentops_workbench.graph.fixed import _CLARIFY_MESSAGE
from agentops_workbench.graph.single_agent import run_single_agent
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


def test_single_agent_executes_search_docs() -> None:
    adapter = _ScriptedAdapter(["TOOL search_docs {}", "ANSWER grounded"])
    out = run_single_agent(adapter, "anything")
    assert out.state == RunState.SUCCEEDED
    assert out.steps == 2
    assert len(out.tool_results) == 1
    assert out.tool_results[0]["tool_name"] == "search_docs"
    assert out.tool_results[0]["outcome"] == "ok"
    assert out.tool_results[0]["error_kind"] is None
    assert out.answer == "grounded"


def test_single_agent_feeds_search_result_back_into_transcript() -> None:
    adapter = _ScriptedAdapter(["TOOL search_docs {}", "ANSWER grounded"])
    run_single_agent(adapter, "anything", document_client=_StubDocumentClient())
    assert len(adapter.calls) == 2
    # The second LLM call's transcript must include the first call's TOOL
    # directive plus a real tool-result message naming what was found.
    second_call_messages = adapter.calls[1]
    joined = " ".join(m["content"] for m in second_call_messages)
    assert "stub-doc" in joined


def test_single_agent_read_document_grounds_transcript_in_retrieved_text() -> None:
    adapter = _ScriptedAdapter(
        ["TOOL search_docs {}", "TOOL read_document {}", "ANSWER grounded"]
    )
    out = run_single_agent(adapter, "anything", document_client=_StubDocumentClient())
    assert out.tool_results[1]["tool_name"] == "read_document"
    assert out.tool_results[1]["outcome"] == "ok"
    third_call_messages = adapter.calls[2]
    joined = " ".join(m["content"] for m in third_call_messages)
    assert "unique-marker-xyz" in joined


def test_document_client_is_injectable() -> None:
    adapter = _ScriptedAdapter(["TOOL search_docs {}", "ANSWER grounded"])
    out = run_single_agent(adapter, "anything", document_client=_StubDocumentClient())
    assert out.tool_results[0]["outcome"] == "ok"


# ---- get_issue: no real backend, must not crash ----


def test_single_agent_get_issue_records_unsupported_capability() -> None:
    adapter = _ScriptedAdapter(["TOOL get_issue {}", "ANSWER no issue backend"])
    out = run_single_agent(adapter, "look up issue ABC-123")
    assert out.state == RunState.SUCCEEDED  # does not crash the run
    assert out.steps == 2
    assert out.tool_results[0]["tool_name"] == "get_issue"
    assert out.tool_results[0]["outcome"] == "error"
    assert out.tool_results[0]["error_kind"] == "unsupported_capability"


def test_single_agent_get_issue_does_not_halt_the_loop() -> None:
    adapter = _ScriptedAdapter(
        ["TOOL get_issue {}", "TOOL search_docs {}", "ANSWER mixed"]
    )
    out = run_single_agent(adapter, "issue ABC-123 and also docs")
    assert out.steps == 3
    assert out.tool_results[0]["outcome"] == "error"
    assert out.tool_results[0]["error_kind"] == "unsupported_capability"
    assert out.tool_results[1]["tool_name"] == "search_docs"
    assert out.tool_results[1]["outcome"] == "ok"


# ---- malformed TOOL directive: no tool name ----


def test_single_agent_tool_without_name_falls_back_to_clarify() -> None:
    adapter = _ScriptedAdapter(["TOOL"])
    out = run_single_agent(adapter, "anything")
    assert out.state == RunState.SUCCEEDED
    assert out.answer == _CLARIFY_MESSAGE
    assert out.tool_results == []
