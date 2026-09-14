"""TicketSystemAdapter -- thin EvidenceSourceAdapter facade over the
EXISTING mocks.tickets.TicketLedger. The extensibility proof for the
customer-support/ticketing axis: zero new domain logic, just the same
Protocol fitted over a domain this repo already has real, tested code
for."""
from __future__ import annotations

import pytest

from agentops_workbench.adapters.base import EvidenceRef
from agentops_workbench.adapters.ticket_system import TicketSystemAdapter
from agentops_workbench.mcp import MCPError
from agentops_workbench.mocks.tickets import TicketLedger


def _seeded_ledger() -> TicketLedger:
    ledger = TicketLedger()
    ledger.publish(
        action_key="k1",
        title="Checkout button unresponsive on mobile",
        body="Tapping checkout does nothing on iOS Safari.",
        published_by="alice",
        args={"x": 1},
    )
    ledger.publish(
        action_key="k2",
        title="Password reset email never arrives",
        body="Requested reset three times, no email received.",
        published_by="bob",
        args={"x": 2},
    )
    ledger.publish(
        action_key="k3",
        title="Feature request: dark mode",
        body="Would like a dark theme option in settings.",
        published_by="carol",
        args={"x": 3},
    )
    return ledger


def test_search_evidence_substring_matches_title(tmp_path) -> None:
    adapter = TicketSystemAdapter(ledger=_seeded_ledger())
    results = adapter.search_evidence("checkout")
    assert len(results) == 1
    assert isinstance(results[0], EvidenceRef)
    assert results[0].source_kind == "ticket-system"
    assert results[0].score > 0.0
    assert "Checkout" in results[0].title


def test_search_evidence_substring_matches_body(tmp_path) -> None:
    adapter = TicketSystemAdapter(ledger=_seeded_ledger())
    results = adapter.search_evidence("reset email")
    assert len(results) == 1
    assert "Password reset" in results[0].title


def test_search_evidence_no_match_returns_empty(tmp_path) -> None:
    adapter = TicketSystemAdapter(ledger=_seeded_ledger())
    assert adapter.search_evidence("zzz-no-such-term-zzz") == []


def test_search_evidence_empty_query_returns_all_tickets(tmp_path) -> None:
    adapter = TicketSystemAdapter(ledger=_seeded_ledger())
    results = adapter.search_evidence("")
    assert len(results) == 3


def test_top_k_limits_result_count(tmp_path) -> None:
    adapter = TicketSystemAdapter(ledger=_seeded_ledger())
    results = adapter.search_evidence("", top_k=2)
    assert len(results) == 2


def test_read_evidence_round_trip_by_ticket_id(tmp_path) -> None:
    adapter = TicketSystemAdapter(ledger=_seeded_ledger())
    ref = adapter.search_evidence("dark mode")[0]
    text = adapter.read_evidence(ref.ref_id)
    assert "dark theme" in text
    assert "carol" in text


def test_read_evidence_unknown_ref_id_raises_mcp_error(tmp_path) -> None:
    adapter = TicketSystemAdapter(ledger=_seeded_ledger())
    with pytest.raises(MCPError):
        adapter.read_evidence("not-a-real-ticket-id")


def test_default_constructor_builds_its_own_ledger(tmp_path) -> None:
    adapter = TicketSystemAdapter()
    assert adapter.search_evidence("anything") == []


def test_zero_new_domain_logic_ledger_publish_still_works_underneath(tmp_path) -> None:
    ledger = _seeded_ledger()
    adapter = TicketSystemAdapter(ledger=ledger)
    assert len(adapter.search_evidence("checkout")) == 1
    # The adapter is a read facade -- publishing more tickets through the
    # SAME ledger instance must be reflected in subsequent searches.
    ledger.publish(
        action_key="k4",
        title="Checkout also broken on Android",
        body="Same bug on Android Chrome.",
        published_by="dave",
        args={"x": 4},
    )
    assert len(adapter.search_evidence("checkout")) == 2
