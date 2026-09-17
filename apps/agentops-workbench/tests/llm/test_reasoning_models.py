"""GPT-5-family / o1 / o3 "reasoning" models on OpenAI's Chat Completions
API take `max_completion_tokens` (not `max_tokens`) and an optional
`reasoning_effort` field; older chat models (gpt-4o-mini, MiniMax-M3)
reject an unrecognized `reasoning_effort` param outright, so it must be
omitted entirely rather than sent empty.

`temperature` must ALSO be omitted for a reasoning model -- caught by a
real call to gpt-5.6-luna, not from docs: "Unsupported value: 'temperature'
does not support 0.0 with this model. Only the default (1) value is
supported." Every caller in this codebase (graph/wiki_chat.py included)
calls `.chat()` without an explicit temperature, which means the method's
own default (0.0) gets sent -- exactly the value gpt-5.6-luna rejects.
"""
from __future__ import annotations

import pytest

from agentops_workbench.llm.openai_compat import OpenAICompatAdapter


class _CapturingCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object):
        self.calls.append(kwargs)

        class _Choice:
            class message:  # noqa: N801 - matches openai SDK's nested shape
                content = "ok"

        class _Result:
            choices = [_Choice()]
            usage = None

        return _Result()


def _adapter(model: str, reasoning_effort: str = "") -> tuple[OpenAICompatAdapter, _CapturingCompletions]:
    adapter = OpenAICompatAdapter(
        api_key="test-key", base_url="https://api.openai.com/v1", model=model,
        provider_label="openai", reasoning_effort=reasoning_effort,
    )
    capturing = _CapturingCompletions()
    adapter._client.chat.completions = capturing  # type: ignore[attr-defined]
    return adapter, capturing


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "gpt-5.6-terra", "o1", "o3-mini"])
def test_reasoning_models_use_max_completion_tokens_not_max_tokens(model: str) -> None:
    adapter, capturing = _adapter(model)
    adapter.chat([{"role": "user", "content": "hi"}], max_tokens=2048)
    sent = capturing.calls[0]
    assert "max_completion_tokens" in sent
    assert sent["max_completion_tokens"] == 2048
    assert "max_tokens" not in sent


def test_non_reasoning_model_keeps_max_tokens() -> None:
    adapter, capturing = _adapter("gpt-4o-mini")
    adapter.chat([{"role": "user", "content": "hi"}], max_tokens=2048)
    sent = capturing.calls[0]
    assert sent["max_tokens"] == 2048
    assert "max_completion_tokens" not in sent


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "gpt-5.6-terra", "o1", "o3-mini"])
def test_reasoning_models_never_receive_a_temperature(model: str) -> None:
    """gpt-5.6-luna rejects any temperature but its own default (1) --
    confirmed via a real API call, not assumed. Every caller in this
    codebase calls .chat() with the default temperature=0.0, so a
    reasoning model must have the field omitted entirely rather than
    have 0.0 (or any explicit value) forwarded."""
    adapter, capturing = _adapter(model)
    adapter.chat([{"role": "user", "content": "hi"}])
    assert "temperature" not in capturing.calls[0]


def test_non_reasoning_model_still_sends_temperature() -> None:
    adapter, capturing = _adapter("gpt-4o-mini")
    adapter.chat([{"role": "user", "content": "hi"}], temperature=0.2)
    assert capturing.calls[0]["temperature"] == 0.2


def test_reasoning_effort_is_included_when_configured() -> None:
    adapter, capturing = _adapter("gpt-5.6-luna", reasoning_effort="high")
    adapter.chat([{"role": "user", "content": "hi"}])
    assert capturing.calls[0]["reasoning_effort"] == "high"


def test_reasoning_effort_omitted_when_unset() -> None:
    adapter, capturing = _adapter("gpt-5.6-luna", reasoning_effort="")
    adapter.chat([{"role": "user", "content": "hi"}])
    assert "reasoning_effort" not in capturing.calls[0]


def test_reasoning_effort_never_sent_to_a_non_reasoning_model() -> None:
    """A configured reasoning_effort must not leak into a gpt-4o-mini call
    -- that model rejects the unrecognized field."""
    adapter, capturing = _adapter("gpt-4o-mini", reasoning_effort="high")
    adapter.chat([{"role": "user", "content": "hi"}])
    assert "reasoning_effort" not in capturing.calls[0]
