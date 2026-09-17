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


# ---- provider override (UI picker) ----


def test_factory_provider_override_switches_the_returned_adapter() -> None:
    s = Settings(provider="local-fake", openai_api_key="sk-test")
    a = make_adapter(s, provider="openai")
    assert a.provider == "openai"


def test_factory_override_to_a_different_provider_uses_that_providers_default_model() -> None:
    """Settings.model is tuned for whichever provider is actually
    configured (settings.provider); switching providers via the UI picker
    must not send that model string to a different provider's API."""
    s = Settings(provider="minimax", model="MiniMax-M3", openai_api_key="sk-test")
    a = make_adapter(s, provider="openai")
    assert a.model != "MiniMax-M3"
    assert a.model  # some real default, not empty


def test_factory_override_matching_the_configured_provider_keeps_the_configured_model() -> None:
    s = Settings(provider="openai", model="my-custom-model", openai_api_key="sk-test")
    a = make_adapter(s, provider="openai")
    assert a.model == "my-custom-model"


def test_factory_no_override_behaves_exactly_as_before() -> None:
    s = Settings(provider="local-fake")
    a = make_adapter(s, provider=None)
    assert a.provider == "local-fake"


def test_factory_openai_requires_api_key() -> None:
    s = Settings(provider="openai", openai_api_key="")
    try:
        make_adapter(s)
    except ValueError as exc:
        assert "openai" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError when openai_api_key is empty")


def test_factory_passes_reasoning_effort_through_to_the_openai_adapter() -> None:
    s = Settings(provider="openai", openai_api_key="sk-test", reasoning_effort="high")
    a = make_adapter(s)
    assert a._reasoning_effort == "high"  # noqa: SLF001 - internal knob, no public getter needed
