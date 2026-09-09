"""Factory — picks an adapter by provider name. The graph uses only this."""
from __future__ import annotations

from ..settings import Settings
from .adapter import LLMAdapter
from .local_fake import LocalFakeAdapter
from .minimax import MinimaxAdapter


def make_adapter(settings: Settings) -> LLMAdapter:
    p = settings.provider.lower()
    if p == "local-fake":
        return LocalFakeAdapter()
    if p == "minimax":
        return MinimaxAdapter(
            api_key=settings.minimax_api_key,
            base_url=settings.minimax_base_url,
            model=settings.model,
        )
    if p == "openai":
        # Imported lazily; this branch ships in step 4 experiments
        from .openai_compat import OpenAICompatAdapter

        return OpenAICompatAdapter(
            api_key=settings.openai_api_key,
            base_url="https://api.openai.com/v1",
            model=settings.model,
            provider_label="openai",
        )
    if p == "anthropic":
        from .openai_compat import OpenAICompatAdapter

        return OpenAICompatAdapter(
            api_key=settings.anthropic_api_key,
            base_url="https://api.anthropic.com/v1",
            model=settings.model,
            provider_label="anthropic",
        )
    raise ValueError(f"unknown provider: {p!r}")
