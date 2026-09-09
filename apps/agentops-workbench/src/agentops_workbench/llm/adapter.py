"""LLMAdapter interface — provider-agnostic boundary for the agent graph.

Per ADR-0003: the graph code never names a provider. The adapter is the
only place that maps `provider=` to a concrete chat-model wrapper.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Usage:
    """Normalized token usage and cost returned by every adapter."""

    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class ChatResult:
    """Normalized chat-model result returned by every adapter."""

    content: str
    usage: Usage
    raw: Any = None  # provider-native response (kept for forensics)


class LLMAdapter(ABC):
    """Abstract chat-model adapter. All adapters return ChatResult + Usage."""

    provider: str
    model: str

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kw: Any,
    ) -> ChatResult:
        """Send messages, return ChatResult. Must NOT raise on retriable errors;
        adapter-specific retries live inside the implementation. The graph
        treats any exception as a `failed` state."""

    def close(self) -> None:  # pragma: no cover - default no-op
        """Release any held resources (HTTP clients, etc.)."""
        return None
