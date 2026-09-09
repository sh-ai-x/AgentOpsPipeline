"""TDD regression — LocalFakeAdapter returns deterministic canned responses."""
from __future__ import annotations

from agentops_workbench.llm.local_fake import LocalFakeAdapter


def test_returns_canned_response() -> None:
    a = LocalFakeAdapter()
    r = a.chat([{"role": "user", "content": "What is the Postgres connection string?"}])
    assert r.content  # non-empty
    assert r.usage.provider == "local-fake"
    assert r.usage.model == "local-fake-v1"
    assert r.usage.cost_usd == 0.0


def test_deterministic_cycle() -> None:
    """Same script index produces same response across calls (script replay)."""
    a = LocalFakeAdapter()
    r1 = a.chat([{"role": "user", "content": "hi"}])
    a2 = LocalFakeAdapter()
    r2 = a2.chat([{"role": "user", "content": "hi"}])
    assert r1.content == r2.content


def test_usage_token_count_is_positive() -> None:
    a = LocalFakeAdapter()
    r = a.chat([{"role": "user", "content": "How do I configure LangGraph with Postgres?"}])
    assert r.usage.prompt_tokens > 0
    assert r.usage.total_tokens >= r.usage.prompt_tokens
