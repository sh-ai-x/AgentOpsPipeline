"""TDD regression — factory picks the right adapter per provider name."""
from __future__ import annotations

from agentops_workbench.llm.adapter import LLMAdapter
from agentops_workbench.llm.factory import make_adapter
from agentops_workbench.settings import Settings


def test_factory_local_fake() -> None:
    s = Settings(provider="local-fake")
    a = make_adapter(s)
    assert a.provider == "local-fake"


def test_factory_minimax_requires_api_key() -> None:
    s = Settings(provider="minimax", minimax_api_key="")
    try:
        make_adapter(s)
    except ValueError as exc:
        assert "MINIMAX_API_KEY" in str(exc)
    else:
        raise AssertionError("expected ValueError when minimax_api_key is empty")


def test_factory_unknown_provider_raises() -> None:
    s = Settings(provider="totally-bogus")
    try:
        make_adapter(s)
    except ValueError as exc:
        assert "unknown provider" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown provider")


def test_factory_returns_subclass_of_llm_adapter() -> None:
    s = Settings(provider="local-fake")
    a = make_adapter(s)
    assert isinstance(a, LLMAdapter)
