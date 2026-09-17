"""Normalized LLM-provider error classification.

Mirrors `mcp.classify_mcp_error`'s shape -- a small closed vocabulary a
caller can branch on -- at the LLM-adapter boundary. `LLMAdapter.chat()`
implementations (`MinimaxAdapter`, `OpenAICompatAdapter`) catch their
provider SDK's raw exception and re-raise it wrapped in an
`LLMProviderError` via `classify_llm_error`, so `graph/wiki_chat.py` and
`api/server.py` branch on one small `kind` enum instead of needing to know
every provider SDK's exception hierarchy.

Real incident that motivated this: a MiniMax account ran out of quota
mid-session. The raw `openai.RateLimitError` propagated unhandled through
`_answer_node` -> `/v1/wiki/qa` as a generic 500 with no actionable detail,
and the operator had no way to tell "out of credits" apart from "transient
rate limit, retry in a second" -- two problems with opposite correct
responses (top up vs. wait).
"""
from __future__ import annotations

# MiniMax and OpenAI both surface quota exhaustion as `openai.RateLimitError`
# (HTTP 429) -- the same type AND status code a transient rate limit uses.
# The only distinguishing signal is the error message/body text, so it is
# checked FIRST, before any type- or status-code-based branch below.
_QUOTA_MARKERS = ("insufficient", "quota", "balance", "credit", "余额不足", "配额")


class LLMProviderError(Exception):
    """Normalized LLM-provider call failure.

    `kind` is one of: `quota_exceeded`, `rate_limited`, `auth_failed`,
    `unavailable`, `unknown`.
    """

    def __init__(self, kind: str, provider: str, message: str) -> None:
        super().__init__(f"[{kind}] {provider}: {message}")
        self.kind = kind
        self.provider = provider
        self.message = message


def classify_llm_error(exc: Exception, *, provider: str) -> LLMProviderError:
    """Wrap a raw provider-SDK exception into an `LLMProviderError`.

    `openai` is a hard dependency of this package (`pyproject.toml`), so
    importing it here unconditionally is safe regardless of which
    provider is configured -- `local-fake` never calls this function at
    all since it never raises.
    """
    import openai

    status_code = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    message = str(exc)
    haystack = f"{message} {body}".lower()

    if any(marker in haystack for marker in _QUOTA_MARKERS):
        return LLMProviderError("quota_exceeded", provider, message)
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return LLMProviderError("auth_failed", provider, message)
    if isinstance(exc, openai.RateLimitError) or status_code == 429:
        return LLMProviderError("rate_limited", provider, message)
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return LLMProviderError("unavailable", provider, message)
    return LLMProviderError("unknown", provider, message)
