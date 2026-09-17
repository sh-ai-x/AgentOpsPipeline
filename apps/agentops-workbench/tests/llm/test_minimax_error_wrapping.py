"""MinimaxAdapter / OpenAICompatAdapter must wrap a raw provider SDK
exception into LLMProviderError -- not let it propagate raw. Regression
for the incident where a MiniMax quota-exhaustion error surfaced as an
unhandled 500 with no actionable message (see llm/errors.py docstring)."""
from __future__ import annotations

import httpx
import openai
import pytest

from agentops_workbench.llm.errors import LLMProviderError
from agentops_workbench.llm.minimax import MinimaxAdapter
from agentops_workbench.llm.openai_compat import OpenAICompatAdapter


def _quota_exhausted_error() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.minimax.chat/v1/chat/completions")
    resp = httpx.Response(
        429, json={"error": {"message": "insufficient balance, please recharge"}}, request=request
    )
    return openai.RateLimitError("insufficient balance, please recharge", response=resp, body=resp.json())


def test_minimax_adapter_wraps_a_quota_error_into_llm_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MinimaxAdapter(api_key="test-key", base_url="https://api.minimax.chat/v1", model="MiniMax-M3")

    def _raise(*args: object, **kwargs: object) -> None:
        raise _quota_exhausted_error()

    monkeypatch.setattr(adapter._client.chat.completions, "create", _raise)

    with pytest.raises(LLMProviderError) as exc_info:
        adapter.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.kind == "quota_exceeded"
    assert exc_info.value.provider == "minimax"


def test_openai_compat_adapter_wraps_a_quota_error_into_llm_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OpenAICompatAdapter(
        api_key="test-key", base_url="https://api.openai.com/v1", model="gpt-4o-mini", provider_label="openai"
    )

    def _raise(*args: object, **kwargs: object) -> None:
        raise _quota_exhausted_error()

    monkeypatch.setattr(adapter._client.chat.completions, "create", _raise)

    with pytest.raises(LLMProviderError) as exc_info:
        adapter.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.kind == "quota_exceeded"
    assert exc_info.value.provider == "openai"
