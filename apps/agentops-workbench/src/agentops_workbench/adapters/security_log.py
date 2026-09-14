"""SecurityLogAdapter -- structured JSONL security / authorization log.

Schema (one JSON object per line, UTF-8, `\\n`-delimited):

    {
      "ts": "2026-09-13T04:01:00+00:00",   # ISO-8601, timezone-aware
      "severity": "high" | "low" | ...,     # free-form severity label
      "rule_id": "auth-deny-01",            # the rule/detector that fired
      "message": "denied login for ...",    # human-readable summary
      "source_ip": "10.0.0.5"               # optional, any extra fields
    }                                        # are preserved verbatim

Per ADR-0007, a query string alone is not sufficient for this source: a
security investigation is "show me the high-severity auth denials in this
20-minute window", not a bag-of-words search. `search_evidence` therefore
treats `window` (filter by `ts` inside `[start, end]`, inclusive) and
`filters` (exact-match predicates over any top-level field, e.g.
`{"severity": "high", "rule_id": "auth-deny-01"}`) as the primary
narrowing mechanism, with `query` supported as an *additional* optional
lexical substring filter over `message` -- an empty query matches every
line (after window/filters are applied).

Each `EvidenceRef` from `search_evidence` represents exactly ONE matching
log line -- this is a citable log line, not an aggregate (that shape is
`IncidentLogAdapter`'s job). `ref_id` is a stable hash of the line's exact
JSON text, so the same line always resolves to the same ref_id across
repeated searches. `read_evidence` returns that line's full JSON,
pretty-printed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..mcp import MCPError
from .base import EvidenceRef


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _line_ref_id(raw_line: str) -> str:
    return "sec:" + hashlib.sha256(raw_line.encode("utf-8")).hexdigest()[:16]


class SecurityLogAdapter:
    """Structured JSONL security-log adapter. See module docstring for schema."""

    source_kind = "security-log"

    def __init__(self, log_path: str) -> None:
        self._log_path = log_path
        self._records: dict[str, dict[str, Any]] = {}
        path = Path(log_path)
        if path.exists():
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                ref_id = _line_ref_id(raw_line)
                self._records[ref_id] = json.loads(raw_line)

    @staticmethod
    def _in_window(ts: str, window: tuple[str, str]) -> bool:
        start, end = window
        return start <= ts <= end

    def search_evidence(
        self,
        query: str,
        top_k: int = 5,
        *,
        window: tuple[str, str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceRef]:
        query_lower = query.lower().strip()
        retrieved_at = _now_iso()
        scored: list[EvidenceRef] = []
        for ref_id, record in self._records.items():
            ts = record.get("ts", "")
            if window is not None and not self._in_window(ts, window):
                continue
            if filters:
                if any(record.get(key) != value for key, value in filters.items()):
                    continue
            message = str(record.get("message", ""))
            if query_lower:
                if query_lower not in message.lower():
                    continue
                score = float(message.lower().count(query_lower))
            else:
                score = 1.0
            title = f"{record.get('rule_id', 'unknown-rule')}: {message}"[:120]
            scored.append(
                EvidenceRef(
                    ref_id=ref_id,
                    title=title,
                    score=score,
                    source_kind=self.source_kind,
                    retrieved_at=retrieved_at,
                )
            )
        scored.sort(key=lambda r: (-r.score, r.ref_id))
        return scored[:top_k]

    def read_evidence(self, ref_id: str, offset: int = 0, limit: int = 2000) -> str:
        record = self._records.get(ref_id)
        if record is None:
            raise MCPError("unknown", f"log line not found: {ref_id}", source="security_log")
        text = json.dumps(record, indent=2, sort_keys=True)
        return text[offset : offset + limit]
