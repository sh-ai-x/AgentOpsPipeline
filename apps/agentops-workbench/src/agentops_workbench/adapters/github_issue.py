"""GitHubIssueAdapter -- real GitHub REST API v3 search over one repo's
issues, via `httpx`.

Endpoints used (both documented at https://docs.github.com/en/rest):
  - Search:  GET /search/issues?q=repo:{owner}/{repo}+{query}
             https://docs.github.com/en/rest/search/search#search-issues-and-pull-requests
  - Read:    GET /repos/{owner}/{repo}/issues/{issue_number}
             https://docs.github.com/en/rest/issues/issues#get-an-issue

Token resolution: the explicit `token` constructor arg wins; otherwise
falls back to the `AGENTOPS_GITHUB_TOKEN` env var, matching this
project's `AGENTOPS_` env-var convention (see `AGENTOPS_EVIDENCE_SOURCES`
in ADR-0007). An unauthenticated adapter still works against public repos
at GitHub's much lower unauthenticated rate limit.

Every non-2xx response and every network-level exception is normalized
through `classify_mcp_error` -- this module raises no exception type of
its own.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from ..mcp import classify_mcp_error
from .base import EvidenceRef

_API_BASE = "https://api.github.com"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _GitHubStatusError(RuntimeError):
    """Synthetic exception carrying enough text for `classify_mcp_error`'s
    keyword-based bucketing to place a non-2xx GitHub response correctly.
    """


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    snippet = resp.text[:200]
    if resp.status_code in (401, 403):
        raise _GitHubStatusError(
            f"permission denied by GitHub API: {resp.status_code} {snippet}"
        )
    if resp.status_code == 404:
        raise _GitHubStatusError(f"GitHub resource not found: 404 {snippet}")
    raise _GitHubStatusError(f"GitHub API error {resp.status_code}: {snippet}")


class GitHubIssueAdapter:
    """Search + read GitHub Issues for one `owner/repo`."""

    source_kind = "github-issue"

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | None = None,
        *,
        base_url: str = _API_BASE,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._owner = owner
        self._repo = repo
        self._token = token if token is not None else os.environ.get("AGENTOPS_GITHUB_TOKEN")
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def search_evidence(
        self,
        query: str,
        top_k: int = 5,
        *,
        window: tuple[str, str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceRef]:
        q = f"repo:{self._owner}/{self._repo}"
        if query.strip():
            q += f" {query.strip()}"
        for key, value in (filters or {}).items():
            q += f" {key}:{value}"
        if window is not None:
            start, end = window
            q += f" created:{start[:10]}..{end[:10]}"

        try:
            resp = self._client.get(
                "/search/issues",
                params={"q": q, "per_page": top_k},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise classify_mcp_error(exc) from exc
        try:
            _raise_for_status(resp)
        except _GitHubStatusError as exc:
            raise classify_mcp_error(exc) from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise classify_mcp_error(exc) from exc

        retrieved_at = _now_iso()
        results: list[EvidenceRef] = []
        for item in data.get("items", [])[:top_k]:
            results.append(
                EvidenceRef(
                    ref_id=str(item["number"]),
                    title=item.get("title", ""),
                    score=float(item.get("score") or 0.0),
                    source_kind=self.source_kind,
                    retrieved_at=retrieved_at,
                )
            )
        return results

    def read_evidence(self, ref_id: str, offset: int = 0, limit: int = 2000) -> str:
        try:
            resp = self._client.get(
                f"/repos/{self._owner}/{self._repo}/issues/{ref_id}",
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise classify_mcp_error(exc) from exc
        try:
            _raise_for_status(resp)
        except _GitHubStatusError as exc:
            raise classify_mcp_error(exc) from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise classify_mcp_error(exc) from exc

        body = data.get("body") or ""
        return body[offset : offset + limit]
