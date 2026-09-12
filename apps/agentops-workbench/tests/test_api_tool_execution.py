"""TDD regression — wiring `_execute_run` through topology.run_topology() by
graph_version, and persisting real ToolCall rows for planner-executor-v1.

Coverage:
  - graph_version -> topology dispatch: fixed-v1 / single-agent-v1 /
    planner-executor-v1 map to the fixed / single_agent / planner_executor
    topologies. An unknown graph_version is rejected at creation (422).
  - fixed-v1 and single-agent-v1 make zero tool calls (unchanged, by design).
  - planner-executor-v1 persists one ToolCall row per executed step when the
    plan actually runs tools: outcome="ok" for search_docs/read_document,
    outcome="error" + error_kind="unsupported_capability" for get_issue.
    Either way the run still reaches state=succeeded.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentops_workbench.api.server import app, issue_token
from agentops_workbench.db.session import reset_for_tests
from agentops_workbench.llm.adapter import ChatResult, LLMAdapter, Usage


class _ScriptedAdapter(LLMAdapter):
    provider = "scripted-test"
    model = "scripted-v1"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._last_usage: Usage | None = None

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kw: Any,
    ) -> ChatResult:
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


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("AGENTOPS_DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("AGENTOPS_PROVIDER", "local-fake")
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _bearer(principal: str = "alice") -> dict[str, str]:
    tok = issue_token(principal)
    return {"Authorization": f"Bearer {tok}"}


# ---- graph_version -> topology dispatch ----


def test_unknown_graph_version_returns_422(client: TestClient) -> None:
    r = client.post(
        "/v1/runs",
        json={"task": "hi", "graph_version": "nonexistent-v9"},
        headers=_bearer(),
    )
    assert r.status_code == 422


def test_fixed_v1_dispatches_and_makes_no_tool_calls(client: TestClient) -> None:
    r = client.post(
        "/v1/runs",
        json={"task": "How do I configure LangGraph?", "graph_version": "fixed-v1"},
        headers=_bearer(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["tool_calls"] == []


def test_single_agent_v1_dispatches_and_makes_no_tool_calls(client: TestClient) -> None:
    r = client.post(
        "/v1/runs",
        json={"task": "How do I configure LangGraph?", "graph_version": "single-agent-v1"},
        headers=_bearer(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["state"] in {"succeeded", "failed"}
    assert body["tool_calls"] == []


# ---- planner-executor-v1: real ToolCall persistence ----


def test_planner_executor_v1_persists_tool_calls_for_search_and_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_text = "step: search_docs\nstep: read_document"
    synth_text = "ANSWER: grounded"
    scripted = _ScriptedAdapter([plan_text, synth_text])
    monkeypatch.setattr(
        "agentops_workbench.api.server.make_adapter", lambda settings: scripted
    )

    r = client.post(
        "/v1/runs",
        json={
            "task": "Explain PostgresCheckpointer persistence in LangGraph",
            "graph_version": "planner-executor-v1",
        },
        headers=_bearer(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["state"] == "succeeded"
    assert len(body["tool_calls"]) == 2
    names = [tc["tool_name"] for tc in body["tool_calls"]]
    assert names == ["search_docs", "read_document"]
    for tc in body["tool_calls"]:
        assert tc["outcome"]["status"] == "ok"
        assert tc["policy_decision"]
        assert tc["action_key"]


def test_planner_executor_v1_records_get_issue_as_error_and_still_succeeds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_text = "step: get_issue"
    synth_text = "ANSWER: cannot fetch issue"
    scripted = _ScriptedAdapter([plan_text, synth_text])
    monkeypatch.setattr(
        "agentops_workbench.api.server.make_adapter", lambda settings: scripted
    )

    r = client.post(
        "/v1/runs",
        json={"task": "look up issue ABC-123", "graph_version": "planner-executor-v1"},
        headers=_bearer(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["state"] == "succeeded"  # does not crash the run
    assert len(body["tool_calls"]) == 1
    tc = body["tool_calls"][0]
    assert tc["tool_name"] == "get_issue"
    assert tc["outcome"]["status"] == "error"
    assert tc["outcome"]["error_kind"] == "unsupported_capability"


def test_planner_executor_v1_tool_call_args_canonical_uses_real_args(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """args_canonical must be the REAL tool args, stored as a dict (the
    column is JSON-typed) -- not a {"tool_name", "step_index"} placeholder
    encoded as a double-JSON string. The crash-recovery idempotency
    invariant (graph/state.py:make_action_key) is keyed on what was
    actually invoked, not step position."""
    task = "Explain PostgresCheckpointer persistence in LangGraph"
    plan_text = "step: search_docs\nstep: read_document"
    synth_text = "ANSWER: grounded"
    scripted = _ScriptedAdapter([plan_text, synth_text])
    monkeypatch.setattr(
        "agentops_workbench.api.server.make_adapter", lambda settings: scripted
    )

    r = client.post(
        "/v1/runs",
        json={"task": task, "graph_version": "planner-executor-v1"},
        headers=_bearer(),
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]

    from agentops_workbench.db.models import Run
    from agentops_workbench.db.session import session_scope

    with session_scope() as s:
        run = s.get(Run, run_id)
        rows = sorted(run.tool_calls, key=lambda tc: tc.created_at)
        assert len(rows) == 2
        assert isinstance(rows[0].args_canonical, dict)
        assert rows[0].tool_name == "search_docs"
        assert rows[0].args_canonical == {"query": task}
        assert isinstance(rows[1].args_canonical, dict)
        assert rows[1].tool_name == "read_document"
        assert "doc_id" in rows[1].args_canonical


def test_planner_executor_v1_with_local_fake_makes_no_tool_calls(client: TestClient) -> None:
    """local-fake can't produce a parseable plan (no scripted plan text),
    so it still short-circuits to refuse with zero tool calls -- this is
    the CI-default behavior and must remain unchanged."""
    r = client.post(
        "/v1/runs",
        json={"task": "anything", "graph_version": "planner-executor-v1"},
        headers=_bearer(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["tool_calls"] == []
