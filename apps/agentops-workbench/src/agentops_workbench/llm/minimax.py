"""MinimaxAdapter — OpenAI-compatible client pointed at MiniMax's API.

Per ADR-0003: `langchain-minimax` is not yet published on PyPI
(langchain-ai/langchain#36291). Until it lands, we use `openai.OpenAI`
directly with `base_url=MINIMAX_BASE_URL`. The adapter is the only place
that names the provider.
"""
from __future__ import annotations

from typing import Any

from .adapter import ChatResult, LLMAdapter, Usage
from .pricing import cost_usd


class MinimaxAdapter(LLMAdapter):
    provider = "minimax"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        if not api_key:
            raise ValueError("MINIMAX_API_KEY is required for the minimax adapter")
        self.model = model
        # Imported lazily so CI smoke runs without the package installed
        from openai import OpenAI  # type: ignore[import-not-found]

        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kw: Any,
    ) -> ChatResult:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            **kw,
        )
        content = (resp.choices[0].message.content or "").strip()
        u = resp.usage
        usage = Usage(
            provider=self.provider,
            model=self.model,
            prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(u, "completion_tokens", 0) or 0,
            total_tokens=getattr(u, "total_tokens", 0) or 0,
            cost_usd=cost_usd(
                getattr(self, "model", "unknown"),
                getattr(u, "prompt_tokens", 0) or 0,
                getattr(u, "completion_tokens", 0) or 0,
            ),
        )
        self._last_usage = usage
        return ChatResult(content=content, usage=usage, raw=resp)
