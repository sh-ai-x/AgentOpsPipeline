"""EvidenceSourceAdapter Protocol (ADR-0007).

Generalizes `mcp.DocumentClient` (`search_docs`/`read_document`, one
document corpus) into a Protocol that also fits sources that are not a
lexically-searchable document corpus at all: a time-windowed structured
log, a mutable third-party API resource, or a domain this repo already
has real code for (customer-support tickets).

    search_evidence(query, top_k=5, *, window=None, filters=None) -> list[EvidenceRef]
    read_evidence(ref_id, offset=0, limit=2000) -> str

`window`/`filters` exist because a log source cannot answer a bare
lexical query the way a doc corpus can: "the last 20 minutes of 429s" is
a time window plus a structured predicate, not a string to substring-match
against. Adapters for which a plain lexical query is the whole story
(the wiki, the ticket ledger) simply ignore `window`/`filters` when the
caller does not pass them.

`list_filesystem_files` from the old `DocumentClient` Protocol is
deliberately NOT part of this Protocol -- it described the pinned
`@modelcontextprotocol/server-filesystem` transport and nothing else, and
not every adapter (an HTTP-backed one, a SQL-backed one) can honour it.

`MCPError`/`classify_mcp_error` are re-exported (not duplicated) from
`..mcp` so every adapter module has one place to get error normalization
from -- the same `timeout / disconnect / malformed /
unsupported_capability / permission_denied / unknown` vocabulary already
used by `graph/planner_executor.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..mcp import MCPError, classify_mcp_error

__all__ = [
    "EvidenceRef",
    "EvidenceSourceAdapter",
    "MCPError",
    "classify_mcp_error",
]


@dataclass(frozen=True)
class EvidenceRef:
    """A single citable unit of evidence returned by `search_evidence`.

    `ref_id` is opaque and adapter-minted -- callers must not parse it,
    only pass it back to `read_evidence`. `source_kind` is what a
    downstream citation renders (e.g. "wiki", "security-log",
    "incident-log", "github-issue", "ticket-system") and what a
    groundedness scorer would group by. `retrieved_at` is an ISO-8601 UTC
    timestamp: two of the adapters in this package back mutable state (a
    log window slides, a GitHub issue gets edited), so a citation without
    a retrieval timestamp is not reproducible.
    """

    ref_id: str
    title: str
    score: float
    source_kind: str
    retrieved_at: str


class EvidenceSourceAdapter(Protocol):
    """The one seam every evidence source implements, per ADR-0007."""

    def search_evidence(
        self,
        query: str,
        top_k: int = 5,
        *,
        window: tuple[str, str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceRef]: ...

    def read_evidence(self, ref_id: str, offset: int = 0, limit: int = 2000) -> str: ...
