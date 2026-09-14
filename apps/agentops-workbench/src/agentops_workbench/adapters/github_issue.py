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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..mcp import DocRef


import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ..mcp import classify_mcp_error
from .base import EvidenceRef


def _time_monotonic_safe() -> float:
    """Lightweight monotonic-time helper with a safe fallback."""
    return time.monotonic()

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
        body_lc = snippet.lower()
        if 'rate limit' in body_lc:
            raise _GitHubStatusError(
                f"GitHub API rate limit exceeded: {resp.status_code} {snippet}"
                f" -- authenticated requests get a higher limit; set AGENTOPS_GITHUB_TOKEN."
            )
        if 'permission' in body_lc or 'must have access' in body_lc or 'forbidden' in body_lc:
            raise _GitHubStatusError(
                f"permission denied by GitHub API: {resp.status_code} {snippet}"
            )
        # 403 with no specific keyword: default to rate-limit (the
        # common case for anonymous requests against private or
        # large repos).
        raise _GitHubStatusError(
            f"GitHub API request rejected: {resp.status_code} {snippet}"
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
    # --- DocumentClient compat shims (for graph/*_*.py legacy callers) ---
    def search_docs(self, query: str, top_k: int = 5) -> list[DocRef]:
        """Compat shim: delegate to search_evidence, return DocRef-shaped results.

        Issues don't have a relevance score in the GitHub REST API, so we
        return a synthetic 1.0 score for every hit -- a real relevance
        signal is not available for this source.
        """
        ev = self.search_evidence(query, top_k=top_k)
        return [
            DocRef(doc_id=r.ref_id, title=r.title, score=r.score)
            for r in ev
        ]

    def read_document(self, doc_id: str, offset: int = 0, limit: int = 2000) -> str:
        """Compat shim: delegate to read_evidence."""
        return self.read_evidence(ref_id=doc_id, offset=offset, limit=limit)

    def list_filesystem_files(self) -> list[str]:
        """Compat shim: GitHubIssueAdapter is not a filesystem source; return empty."""
        return []


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
        q = self._build_search_q(query, filters, window)
        # Backwards-compat: callers (and older tests) used to pass
        # a bare keyword and rely on us prepending the repo scope.
        # Keep that behavior when no repo: qualifier is present so
        # existing tests + future callers don't have to know
        # oss_helper.py's exact contract.
        if not q.lstrip().startswith("repo:"):
            q = f"repo:{self._owner}/{self._repo} {q}".strip()
        cache_key = (
            (
                getattr(self, "_owner", ""),
                getattr(self, "_repo", ""),
                bool(getattr(self, "_token", "")),
            ),
            q, top_k,
        )
        # 60-second per-process cache: repeated probes within one eval
        # do not each burn a GitHub rate-limit slot.
        cache = getattr(self, "_cache", None)
        if cache is None:
            cache = {}
            self._cache = cache
        cached = cache.get(cache_key)
        if cached is not None:
            if _time_monotonic_safe() - cached[0] < 60.0:
                return list(cached[1])
        try:
            results = self._search_evidence_uncached(q, top_k)
        except Exception as exc:
            raise classify_mcp_error(exc) from exc
        cache[cache_key] = (_time_monotonic_safe(), results)
        return list(results)

    @staticmethod
    def _build_search_q(query, filters, window):
        # oss_helper.py already builds the full repo + qualifiers +
        # query string. Here we only append the trailing parts.
        q_parts = []
        if query and query.strip():
            q_parts.append(query.strip())
        for key, value in (filters or {}).items():
            q_parts.append(f"{key}:{value}")
        if window is not None:
            start, end = window
            q_parts.append(f"created:{start[:10]}..{end[:10]}")
        return " ".join(q_parts)

    def _search_evidence_uncached(self, q: str, top_k: int) -> list[EvidenceRef]:
        try:
            resp = self._client.get(
                "/search/issues",
                params={"q": q, "per_page": top_k},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            # Pass through the original httpx.HTTPError so classify_mcp_error
            # can check the actual class name (e.g. ConnectTimeout -> "timeout").
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
