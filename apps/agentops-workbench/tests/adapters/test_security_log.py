"""SecurityLogAdapter -- structured JSONL security log, one EvidenceRef per
matching log line. window/filters actually narrow results; query is an
optional additional lexical filter over `message`."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentops_workbench.adapters.base import EvidenceRef
from agentops_workbench.adapters.security_log import SecurityLogAdapter
from agentops_workbench.mcp import MCPError

_LINES = [
    {
        "ts": "2026-09-13T04:01:00+00:00",
        "severity": "high",
        "rule_id": "auth-deny-01",
        "message": "denied login for user bob from 10.0.0.5",
        "source_ip": "10.0.0.5",
    },
    {
        "ts": "2026-09-13T04:05:00+00:00",
        "severity": "low",
        "rule_id": "rate-limit-01",
        "message": "rate limit exceeded for client 10.0.0.9",
        "source_ip": "10.0.0.9",
    },
    {
        "ts": "2026-09-13T05:30:00+00:00",
        "severity": "high",
        "rule_id": "auth-deny-01",
        "message": "denied login for user carol from 10.0.0.7",
        "source_ip": "10.0.0.7",
    },
]


def _write_log(tmp_path: Path) -> Path:
    log_path = tmp_path / "security.jsonl"
    log_path.write_text(
        "\n".join(json.dumps(line) for line in _LINES) + "\n", encoding="utf-8"
    )
    return log_path


def test_search_evidence_one_ref_per_matching_line(tmp_path: Path) -> None:
    adapter = SecurityLogAdapter(log_path=str(_write_log(tmp_path)))
    results = adapter.search_evidence("denied login")
    assert len(results) == 2
    assert all(isinstance(r, EvidenceRef) for r in results)
    assert all(r.source_kind == "security-log" for r in results)
    assert all(r.score > 0.0 for r in results)


def test_window_filters_by_ts_range(tmp_path: Path) -> None:
    adapter = SecurityLogAdapter(log_path=str(_write_log(tmp_path)))
    results = adapter.search_evidence(
        "", window=("2026-09-13T04:00:00+00:00", "2026-09-13T04:10:00+00:00")
    )
    assert len(results) == 2
    for r in results:
        line = json.loads(adapter.read_evidence(r.ref_id))
        assert "2026-09-13T04:0" in line["ts"]


def test_filters_exact_match_on_severity_and_rule_id(tmp_path: Path) -> None:
    adapter = SecurityLogAdapter(log_path=str(_write_log(tmp_path)))
    results = adapter.search_evidence("", filters={"severity": "high"})
    assert len(results) == 2
    for r in results:
        line = json.loads(adapter.read_evidence(r.ref_id))
        assert line["severity"] == "high"

    results2 = adapter.search_evidence("", filters={"rule_id": "rate-limit-01"})
    assert len(results2) == 1
    assert json.loads(adapter.read_evidence(results2[0].ref_id))["rule_id"] == "rate-limit-01"


def test_window_and_filters_and_query_combine_narrowing(tmp_path: Path) -> None:
    adapter = SecurityLogAdapter(log_path=str(_write_log(tmp_path)))
    results = adapter.search_evidence(
        "carol",
        window=("2026-09-13T00:00:00+00:00", "2026-09-13T23:59:59+00:00"),
        filters={"severity": "high", "rule_id": "auth-deny-01"},
    )
    assert len(results) == 1
    line = json.loads(adapter.read_evidence(results[0].ref_id))
    assert "carol" in line["message"]


def test_no_query_or_filters_returns_every_line(tmp_path: Path) -> None:
    adapter = SecurityLogAdapter(log_path=str(_write_log(tmp_path)))
    results = adapter.search_evidence("")
    assert len(results) == 3


def test_read_evidence_returns_full_json_of_that_line(tmp_path: Path) -> None:
    adapter = SecurityLogAdapter(log_path=str(_write_log(tmp_path)))
    results = adapter.search_evidence("rate limit")
    text = adapter.read_evidence(results[0].ref_id)
    parsed = json.loads(text)
    assert parsed["rule_id"] == "rate-limit-01"
    assert parsed["source_ip"] == "10.0.0.9"


def test_read_evidence_unknown_ref_id_raises_mcp_error(tmp_path: Path) -> None:
    adapter = SecurityLogAdapter(log_path=str(_write_log(tmp_path)))
    with pytest.raises(MCPError):
        adapter.read_evidence("not-a-real-ref")


def test_ref_ids_are_stable_across_repeated_searches(tmp_path: Path) -> None:
    adapter = SecurityLogAdapter(log_path=str(_write_log(tmp_path)))
    first = {r.ref_id for r in adapter.search_evidence("")}
    second = {r.ref_id for r in adapter.search_evidence("")}
    assert first == second
    assert len(first) == 3
