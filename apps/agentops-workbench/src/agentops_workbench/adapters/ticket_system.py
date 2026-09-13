"""TicketSystemAdapter -- thin EvidenceSourceAdapter facade over the
EXISTING `mocks.tickets.TicketLedger`.

This is the extensibility proof for the customer-support/ticketing axis
named in ADR-0007: it invents no new domain logic. `TicketLedger` already
existed with a real, tested `publish()`/`count()` API from this project's
original support-ops scope; the only addition made to that file is a
read-only `list_tickets()`/`get_ticket()` pair (purely additive, does not
change `publish()`'s behaviour -- see `tests/test_api_runs.py` and
`tests/mcp/test_document_server.py`'s ticket-ledger tests, unchanged).
This module just wraps that in the same `search_evidence`/`read_evidence`
shape every other adapter in this package exposes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..mcp import MCPError
from ..mocks.tickets import TicketLedger
from .base import EvidenceRef


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TicketSystemAdapter:
    """Search + read published tickets via an injected (or default) `TicketLedger`."""

    source_kind = "ticket-system"

    def __init__(self, ledger: TicketLedger | None = None) -> None:
        self._ledger = ledger if ledger is not None else TicketLedger()

    def search_evidence(
        self,
        query: str,
        top_k: int = 5,
        *,
        window: tuple[str, str] | None = None,
        filters: dict | None = None,
    ) -> list[EvidenceRef]:
        query_lower = query.lower().strip()
        retrieved_at = _now_iso()
        scored: list[EvidenceRef] = []
        for ticket in self._ledger.list_tickets():
            haystack = f"{ticket.title}\n{ticket.body}".lower()
            if query_lower:
                hits = haystack.count(query_lower)
                if hits == 0:
                    continue
                score = float(hits)
            else:
                score = 1.0
            scored.append(
                EvidenceRef(
                    ref_id=ticket.id,
                    title=ticket.title,
                    score=score,
                    source_kind=self.source_kind,
                    retrieved_at=retrieved_at,
                )
            )
        scored.sort(key=lambda r: -r.score)
        return scored[:top_k]

    def read_evidence(self, ref_id: str, offset: int = 0, limit: int = 2000) -> str:
        ticket = self._ledger.get_ticket(ref_id)
        if ticket is None:
            raise MCPError("unknown", f"ticket not found: {ref_id}", source="ticket_system")
        text = (
            f"Ticket {ticket.id}\n"
            f"Title: {ticket.title}\n"
            f"Published by: {ticket.published_by}\n"
            f"Created at: {ticket.created_at}\n"
            f"\n{ticket.body}"
        )
        return text[offset : offset + limit]
