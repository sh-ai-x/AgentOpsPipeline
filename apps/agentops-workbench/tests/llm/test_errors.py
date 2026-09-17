"""LLMProviderError / classify_llm_error -- normalized LLM-provider error
classification, mirroring `mcp.classify_mcp_error`'s shape.

Triggered by a real incident: a MiniMax account ran out of quota mid-session
and the raw `openai.RateLimitError` propagated as an unhandled 500 with no
actionable message. Quota exhaustion and a transient rate limit share the
same `openai.RateLimitError` type and HTTP 429 status on MiniMax's
OpenAI-compatible API, so classification must sniff the error body/message
for quota wording FIRST, before falling back to type/status-code checks --
otherwise the two get conflated and an operator burning through a wait-and-
retry loop that will never succeed on an empty account.
"""
from __future__ import annotations

import httpx
import openai
import pytest

from agentops_workbench.llm.errors import LLMProviderError, classify_llm_error


def _response(status_code: int, body: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    return httpx.Response(status_code, json=body, request=request)


def test_rate_limit_error_with_quota_wording_classifies_as_quota_exceeded() -> None:
    resp = _response(429, {"error": {"message": "You have run out of quota, please top up your balance."}})
    exc = openai.RateLimitError(
        "You have run out of quota, please top up your balance.", response=resp, body=resp.json()
    )
    result = classify_llm_error(exc, provider="minimax")
    assert result.kind == "quota_exceeded"
    assert result.provider == "minimax"


def test_rate_limit_error_without_quota_wording_classifies_as_rate_limited() -> None:
    resp = _response(429, {"error": {"message": "Too many requests, slow down."}})
    exc = openai.RateLimitError("Too many requests, slow down.", response=resp, body=resp.json())
    result = classify_llm_error(exc, provider="minimax")
    assert result.kind == "rate_limited"


def test_authentication_error_classifies_as_auth_failed() -> None:
    resp = _response(401, {"error": {"message": "Invalid API key"}})
    exc = openai.AuthenticationError("Invalid API key", response=resp, body=resp.json())
    result = classify_llm_error(exc, provider="openai")
    assert result.kind == "auth_failed"


def test_permission_denied_error_classifies_as_auth_failed() -> None:
    resp = _response(403, {"error": {"message": "Forbidden"}})
    exc = openai.PermissionDeniedError("Forbidden", response=resp, body=resp.json())
    result = classify_llm_error(exc, provider="openai")
    assert result.kind == "auth_failed"


def test_api_connection_error_classifies_as_unavailable() -> None:
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    exc = openai.APIConnectionError(message="Connection refused", request=request)
    result = classify_llm_error(exc, provider="minimax")
    assert result.kind == "unavailable"


def test_api_timeout_error_classifies_as_unavailable() -> None:
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    exc = openai.APITimeoutError(request=request)
    result = classify_llm_error(exc, provider="minimax")
    assert result.kind == "unavailable"


def test_status_code_429_fallback_classifies_as_rate_limited() -> None:
    """A non-openai-typed exception that merely carries a `status_code`
    attribute (e.g. a raw httpx error surfaced by a future adapter) still
    classifies correctly via duck typing."""

    class _FakeError(Exception):
        status_code = 429

    result = classify_llm_error(_FakeError("rate limited"), provider="custom")
    assert result.kind == "rate_limited"


def test_unclassifiable_error_falls_back_to_unknown() -> None:
    result = classify_llm_error(ValueError("something else entirely"), provider="minimax")
    assert result.kind == "unknown"


def test_llm_provider_error_message_includes_kind_and_provider() -> None:
    err = LLMProviderError("quota_exceeded", "minimax", "balance is zero")
    assert "quota_exceeded" in str(err)
    assert "minimax" in str(err)
    assert err.kind == "quota_exceeded"
    assert err.provider == "minimax"
    assert err.message == "balance is zero"


def test_classify_llm_error_returns_a_raisable_exception() -> None:
    result = classify_llm_error(ValueError("boom"), provider="minimax")
    with pytest.raises(LLMProviderError):
        raise result
