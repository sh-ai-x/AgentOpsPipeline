"""GitHubIssueAdapter -- real GitHub REST v3 shapes, zero live network calls.

Every request goes through `pytest_httpx`'s `httpx_mock` fixture: no test
in this module reaches the real network. URLs with query strings are
matched via a compiled regex prefix (pytest_httpx's exact-URL matching
otherwise requires the response's registered query params to equal the
request's byte-for-byte, which we don't want to hard-code here).
"""
from __future__ import annotations

import re

import httpx
import pytest

from agentops_workbench.adapters.base import EvidenceRef
from agentops_workbench.adapters.github_issue import GitHubIssueAdapter
from agentops_workbench.mcp import MCPError

_SEARCH_URL_RE = re.compile(r"^https://api\.github\.com/search/issues(\?.*)?$")

_SEARCH_RESPONSE = {
    "total_count": 2,
    "incomplete_results": False,
    "items": [
        {
            "number": 42,
            "title": "PostgresCheckpointer leaks connections under load",
            "state": "open",
            "score": 4.2,
            "html_url": "https://github.com/acme/widget/issues/42",
            "body": "Full body text of issue 42.",
        },
        {
            "number": 7,
            "title": "Checkpointer occasionally times out",
            "state": "closed",
            "score": 1.1,
            "html_url": "https://github.com/acme/widget/issues/7",
            "body": "Full body text of issue 7.",
        },
    ],
}

_ISSUE_42 = {
    "number": 42,
    "title": "PostgresCheckpointer leaks connections under load",
    "state": "open",
    "body": "Detailed repro steps: run 1000 checkpoints, observe fd leak.",
    "html_url": "https://github.com/acme/widget/issues/42",
}


def test_search_evidence_parses_real_github_search_response_shape(httpx_mock) -> None:
    httpx_mock.add_response(url=_SEARCH_URL_RE, json=_SEARCH_RESPONSE)
    adapter = GitHubIssueAdapter(owner="acme", repo="widget", token="tok123")

    results = adapter.search_evidence("checkpointer")

    assert len(results) == 2
    assert all(isinstance(r, EvidenceRef) for r in results)
    assert results[0].ref_id == "42"
    assert "PostgresCheckpointer" in results[0].title
    assert results[0].score == 4.2
    assert results[0].source_kind == "github-issue"


def test_search_evidence_sends_repo_scoped_query_and_auth_header(httpx_mock) -> None:
    httpx_mock.add_response(url=_SEARCH_URL_RE, json=_SEARCH_RESPONSE)
    adapter = GitHubIssueAdapter(owner="acme", repo="widget", token="tok123")
    adapter.search_evidence("checkpointer")

    request = httpx_mock.get_requests()[0]
    assert request.headers["authorization"] == "Bearer tok123"
    assert "repo:acme/widget" in request.url.params["q"]
    assert "checkpointer" in request.url.params["q"]


def test_token_falls_back_to_agentops_github_token_env_var(monkeypatch, httpx_mock) -> None:
    monkeypatch.setenv("AGENTOPS_GITHUB_TOKEN", "env-token-xyz")
    httpx_mock.add_response(url=_SEARCH_URL_RE, json=_SEARCH_RESPONSE)
    adapter = GitHubIssueAdapter(owner="acme", repo="widget")
    adapter.search_evidence("checkpointer")

    request = httpx_mock.get_requests()[0]
    assert request.headers["authorization"] == "Bearer env-token-xyz"


def test_top_k_limits_result_count(httpx_mock) -> None:
    httpx_mock.add_response(url=_SEARCH_URL_RE, json=_SEARCH_RESPONSE)
    adapter = GitHubIssueAdapter(owner="acme", repo="widget", token="tok123")
    results = adapter.search_evidence("checkpointer", top_k=1)
    assert len(results) == 1


def test_read_evidence_fetches_issue_body_by_number(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/widget/issues/42",
        json=_ISSUE_42,
    )
    adapter = GitHubIssueAdapter(owner="acme", repo="widget", token="tok123")
    body = adapter.read_evidence("42")
    assert "fd leak" in body


def test_read_evidence_respects_offset_and_limit(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/widget/issues/42",
        json=_ISSUE_42,
        is_reusable=True,
    )
    adapter = GitHubIssueAdapter(owner="acme", repo="widget", token="tok123")
    full = adapter.read_evidence("42")
    sliced = adapter.read_evidence("42", offset=2, limit=5)
    assert sliced == full[2:7]


def test_read_evidence_404_raises_mcp_error(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/widget/issues/9999",
        status_code=404,
        json={"message": "Not Found"},
    )
    adapter = GitHubIssueAdapter(owner="acme", repo="widget", token="tok123")
    with pytest.raises(MCPError):
        adapter.read_evidence("9999")


def test_search_evidence_403_rate_limit_raises_mcp_error_rate_limit(httpx_mock) -> None:
    httpx_mock.add_response(
        url=_SEARCH_URL_RE,
        status_code=403,
        json={"message": "API rate limit exceeded"},
    )
    adapter = GitHubIssueAdapter(owner="acme", repo="widget", token="tok123")
    with pytest.raises(MCPError) as exc_info:
        adapter.search_evidence("checkpointer")
    assert exc_info.value.kind == "rate_limit"


def test_network_error_is_normalized_through_classify_mcp_error(httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ConnectTimeout("connection timed out"))
    adapter = GitHubIssueAdapter(owner="acme", repo="widget", token="tok123")
    with pytest.raises(MCPError) as exc_info:
        adapter.search_evidence("checkpointer")
    assert exc_info.value.kind == "timeout"
