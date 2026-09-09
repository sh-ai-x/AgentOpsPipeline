"""Generic OpenAI-compatible adapter — used for `openai` and `anthropic` (deferred).

Note: Anthropic's API is not actually OpenAI-compatible out of the box; this
adapter is a placeholder that delegates to the openai SDK for `provider=openai`.
The `provider=anthropic` branch is wired but not exercised until step 4.
"""
from __future__ import annotations

from typing import Any

from .adapter import ChatResult, LLMAdapter, Usage


class OpenAICompatAdapter(LLMAdapter):
    def __init__(self, api_key: str, base_url: str, model: str, provider_label: str) -> None:
        if not api_key:
            raise ValueError(f"API key required for provider={provider_label}")
        self.provider = provider_label
        self.model = model
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
        return ChatResult(
            content=content,
            usage=Usage(
                provider=self.provider,
                model=self.model,
                prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(u, "completion_tokens", 0) or 0,
                total_tokens=getattr(u, "total_tokens", 0) or 0,
                cost_usd=0.0,
            ),
            raw=resp,
        )
