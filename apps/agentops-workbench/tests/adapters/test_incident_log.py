"""IncidentLogAdapter -- aggregates AI-incident records (timeouts,
rate-limits, disconnects, ...) into ONE EvidenceRef per (error_kind,
window) combination. A log citation is an aggregate, not a quotation
(ADR-0007's own named requirement)."""
from __future__ import annotations

import re

import pytest

from agentops_workbench.adapters.incident_log import IncidentLogAdapter
from agentops_workbench.mcp import MCPError

_RECORDS = [
    {
        "tool_name": "search_docs",
        "outcome": {"status": "error", "error_kind": "timeout"},
        "created_at": "2026-09-13T04:01:00+00:00",
    },
    {
        "tool_name": "read_document",
        "outcome": {"status": "error", "error_kind": "timeout"},
        "created_at": "2026-09-13T04:05:00+00:00",
    },
    {
        "tool_name": "get_issue",
        "outcome": {"status": "error", "error_kind": "unsupported_capability"},
        "created_at": "2026-09-13T04:07:00+00:00",
    },
    {
        "tool_name": "search_docs",
        "outcome": {"status": "ok", "error_kind": None},
        "created_at": "2026-09-13T04:08:00+00:00",
    },
    {
        "tool_name": "read_document",
        "outcome": {"status": "error", "error_kind": "timeout"},
        "created_at": "2026-09-13T06:30:00+00:00",  # outside the 04:00-04:20 window
    },
]


def test_search_evidence_groups_by_error_kind_within_window() -> None:
    adapter = IncidentLogAdapter(records=_RECORDS)
    results = adapter.search_evidence(
        "", window=("2026-09-13T04:00:00+00:00", "2026-09-13T04:20:00+00:00")
    )
    kinds = {r.title.split()[1] for r in results}  # e.g. "2 timeout errors ..."
    assert "timeout" in kinds
    assert "unsupported_capability" in kinds
    # timeout: 2 matches within window; the 06:30 timeout is excluded.
    timeout_ref = next(r for r in results if "timeout" in r.title)
    assert timeout_ref.score == 2.0
    assert re.match(r"^2 timeout errors between 04:00", timeout_ref.title)
    assert timeout_ref.source_kind == "incident-log"


def test_search_evidence_title_is_a_human_readable_aggregate() -> None:
    adapter = IncidentLogAdapter(records=_RECORDS)
    results = adapter.search_evidence(
        "", window=("2026-09-13T04:00:00+00:00", "2026-09-13T04:20:00+00:00")
    )
    timeout_ref = next(r for r in results if "timeout" in r.title)
    assert "between 04:00" in timeout_ref.title
    assert "04:20" in timeout_ref.title


def test_search_evidence_ignores_successful_calls() -> None:
    adapter = IncidentLogAdapter(records=_RECORDS)
    results = adapter.search_evidence(
        "", window=("2026-09-13T04:00:00+00:00", "2026-09-13T04:20:00+00:00")
    )
    # 2 timeout + 1 unsupported_capability = 2 EvidenceRefs (one per kind).
    assert len(results) == 2
    total_incidents = sum(r.score for r in results)
    assert total_incidents == 3  # not 4 -- the "ok" record must not count


def test_window_excludes_records_outside_range() -> None:
    adapter = IncidentLogAdapter(records=_RECORDS)
    results = adapter.search_evidence(
        "", window=("2026-09-13T04:00:00+00:00", "2026-09-13T04:20:00+00:00")
    )
    timeout_ref = next(r for r in results if "timeout" in r.title)
    assert timeout_ref.score == 2.0  # not 3 -- excludes the 06:30 timeout


def test_filters_by_error_kind_vocabulary() -> None:
    adapter = IncidentLogAdapter(records=_RECORDS)
    results = adapter.search_evidence(
        "",
        window=("2026-09-13T00:00:00+00:00", "2026-09-13T23:59:59+00:00"),
        filters={"error_kind": "timeout"},
    )
    assert len(results) == 1
    assert results[0].score == 3.0  # all 3 timeouts across the whole day


def test_read_evidence_returns_the_full_matching_record_trail() -> None:
    adapter = IncidentLogAdapter(records=_RECORDS)
    results = adapter.search_evidence(
        "", window=("2026-09-13T04:00:00+00:00", "2026-09-13T04:20:00+00:00")
    )
    timeout_ref = next(r for r in results if "timeout" in r.title)
    trail = adapter.read_evidence(timeout_ref.ref_id)
    assert "search_docs" in trail
    assert "read_document" in trail
    assert trail.count("timeout") >= 2


def test_read_evidence_unknown_ref_id_raises_mcp_error() -> None:
    adapter = IncidentLogAdapter(records=_RECORDS)
    with pytest.raises(MCPError):
        adapter.read_evidence("not-a-real-aggregate-ref")


def test_search_evidence_without_window_aggregates_over_everything() -> None:
    adapter = IncidentLogAdapter(records=_RECORDS)
    results = adapter.search_evidence("")
    timeout_ref = next(r for r in results if "timeout" in r.title)
    assert timeout_ref.score == 3.0
