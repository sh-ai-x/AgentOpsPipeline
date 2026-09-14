"""IncidentLogAdapter -- aggregates this project's own AI-incident data:
timeouts, rate-limits, disconnects, and the rest of `classify_mcp_error`'s
`kind` vocabulary (`timeout`, `disconnect`, `malformed`,
`unsupported_capability`, `permission_denied`, `unknown`).

Constructor takes an injectable list of plain dicts shaped like:

    {
      "tool_name": "search_docs",
      "outcome": {"status": "ok" | "error", "error_kind": "timeout" | None},
      "created_at": "2026-09-13T04:01:00+00:00",   # ISO-8601
    }

mirroring `db.models.ToolCall`'s real columns (`tool_name`, `outcome`,
`created_at`) without importing SQLAlchemy or `db/models.py` -- a caller
with a real DB session feeds this adapter a list of dicts built from
`ToolCall` rows; this module never depends on the ORM.

Per ADR-0007's own named requirement, a log citation here is an
AGGREGATE, not a quotation: `search_evidence` with a `window` groups the
error records that fall inside it BY `error_kind` and returns ONE
`EvidenceRef` per (error_kind, window) combination, whose `title` reads
like "47 timeout errors between 04:00-04:20". `read_evidence` on that
`ref_id` returns the full list of underlying matching records -- the
aggregate's evidence trail.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..mcp import MCPError
from .base import EvidenceRef

_DEFAULT_WINDOW = ("0001-01-01T00:00:00+00:00", "9999-12-31T23:59:59+00:00")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hhmm(ts: str) -> str:
    """Extract HH:MM from an ISO-8601 timestamp for the human title."""
    # "2026-09-13T04:01:00+00:00" -> "04:01"
    try:
        return ts.split("T", 1)[1][:5]
    except IndexError:
        return ts


class IncidentLogAdapter:
    """Aggregate-by-error_kind adapter over injected AI-incident records."""

    source_kind = "incident-log"

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = list(records)

    @staticmethod
    def _in_window(ts: str, window: tuple[str, str]) -> bool:
        start, end = window
        return start <= ts <= end

    def _matching(
        self,
        window: tuple[str, str] | None,
        filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        effective_window = window or _DEFAULT_WINDOW
        wanted_kind = (filters or {}).get("error_kind")
        matched: list[dict[str, Any]] = []
        for record in self._records:
            outcome = record.get("outcome") or {}
            if outcome.get("status") != "error":
                continue
            error_kind = outcome.get("error_kind")
            if error_kind is None:
                continue
            ts = record.get("created_at", "")
            if not self._in_window(ts, effective_window):
                continue
            if wanted_kind is not None and error_kind != wanted_kind:
                continue
            matched.append(record)
        return matched

    def search_evidence(
        self,
        query: str,
        top_k: int = 5,
        *,
        window: tuple[str, str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceRef]:
        matched = self._matching(window, filters)
        if not matched:
            return []

        by_kind: dict[str, list[dict[str, Any]]] = {}
        for record in matched:
            error_kind = record["outcome"]["error_kind"]
            by_kind.setdefault(error_kind, []).append(record)

        effective_window = window or _DEFAULT_WINDOW
        window_label = f"{_hhmm(effective_window[0])}-{_hhmm(effective_window[1])}"
        retrieved_at = _now_iso()

        results: list[EvidenceRef] = []
        for error_kind, group in by_kind.items():
            count = len(group)
            title = f"{count} {error_kind} errors between {window_label}"
            # "|"-delimited, not ":"-delimited -- the window bounds are
            # ISO-8601 timestamps and already contain colons. ref_id is a
            # pure deterministic function of (error_kind, window), so
            # read_evidence can recompute the trail without depending on
            # this adapter instance having been searched first.
            ref_id = f"incident:{error_kind}|{effective_window[0]}|{effective_window[1]}"
            results.append(
                EvidenceRef(
                    ref_id=ref_id,
                    title=title,
                    score=float(count),
                    source_kind=self.source_kind,
                    retrieved_at=retrieved_at,
                )
            )

        results.sort(key=lambda r: -r.score)
        return results[:top_k]

    def read_evidence(self, ref_id: str, offset: int = 0, limit: int = 2000) -> str:
        if not ref_id.startswith("incident:"):
            raise MCPError("unknown", f"not an incident aggregate ref: {ref_id}", source="incident_log")
        rest = ref_id[len("incident:") :]
        parts = rest.split("|")
        if len(parts) != 3:
            raise MCPError("unknown", f"malformed incident aggregate ref: {ref_id}", source="incident_log")
        error_kind, start, end = parts
        group = self._matching((start, end), {"error_kind": error_kind})
        if not group:
            raise MCPError(
                "unknown", f"incident aggregate not found: {ref_id}", source="incident_log"
            )
        lines = [
            f"- {r['tool_name']} @ {r['created_at']}: {r['outcome']['error_kind']}"
            for r in group
        ]
        text = "\n".join(lines)
        return text[offset : offset + limit]
