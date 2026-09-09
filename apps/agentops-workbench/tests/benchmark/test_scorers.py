"""TDD regression — step 4 scorers + dataset integrity."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentops_workbench.benchmark.load import held_out_sha256, load_case, load_split
from agentops_workbench.benchmark.scorers import (
    BenchmarkCase,
    reliability,
    retrieval_recall_at_k,
    task_success,
    tool_correctness,
)


@pytest.fixture
def cases_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "fixtures" / "cases"


# ---- Scorer unit tests ----


def test_task_success_substring_match() -> None:
    c = BenchmarkCase(
        id="c1", family_id="straightforward", task="t",
        expected_outcome="Postgres for shared/multi-instance",
        allowed_tools=("search_docs",), source_refs=(),
        reviewer="r", split="dev",
    )
    assert task_success(c, "Use Postgres for shared/multi-instance; Sqlite for single-node dev.") is True


def test_task_success_refusal_match() -> None:
    c = BenchmarkCase(
        id="c1", family_id="missing_evidence", task="t",
        expected_outcome="Insufficient evidence in corpus; supported refusal.",
        allowed_tools=("search_docs",), source_refs=(),
        reviewer="r", split="dev",
    )
    assert task_success(
        c, "Insufficient evidence in the corpus to answer confidently. Please provide more context."
    ) is False  # phrasing differs -> substring fails -> expected behaviour for missing_evidence
    # The agent's actual refusal text is "Insufficient evidence in the corpus to answer confidently."
    # which is NOT a substring of "Insufficient evidence in corpus; supported refusal."
    # So the orchestrator should accept either: either align expected_outcome with the agent's
    # refusal text or score refusal differently. For MVP we align expected_outcome.


def test_task_success_no_answer() -> None:
    c = BenchmarkCase(
        id="c1", family_id="x", task="t", expected_outcome="anything",
        allowed_tools=(), source_refs=(), reviewer="r", split="dev",
    )
    assert task_success(c, None) is False


def test_retrieval_recall_perfect() -> None:
    c = BenchmarkCase(
        id="c1", family_id="multi_doc", task="t", expected_outcome="x",
        allowed_tools=(), source_refs=("a", "b"), reviewer="r", split="dev",
    )
    assert retrieval_recall_at_k(c, ["a", "b", "c"], k=5) == 1.0


def test_retrieval_recall_partial() -> None:
    c = BenchmarkCase(
        id="c1", family_id="multi_doc", task="t", expected_outcome="x",
        allowed_tools=(), source_refs=("a", "b"), reviewer="r", split="dev",
    )
    assert retrieval_recall_at_k(c, ["a", "c"], k=5) == 0.5


def test_retrieval_recall_empty_gold_is_1() -> None:
    c = BenchmarkCase(
        id="c1", family_id="missing_evidence", task="t", expected_outcome="x",
        allowed_tools=(), source_refs=(), reviewer="r", split="dev",
    )
    assert retrieval_recall_at_k(c, [], k=5) == 1.0


def test_tool_correctness_all_allowed() -> None:
    c = BenchmarkCase(
        id="c1", family_id="x", task="t", expected_outcome="x",
        allowed_tools=("search_docs", "read_document"), source_refs=(),
        reviewer="r", split="dev",
    )
    calls = [
        {"tool_name": "search_docs"},
        {"tool_name": "read_document"},
    ]
    assert tool_correctness(c, calls) == 1.0


def test_tool_correctness_one_violation() -> None:
    c = BenchmarkCase(
        id="c1", family_id="x", task="t", expected_outcome="x",
        allowed_tools=("search_docs",), source_refs=(),
        reviewer="r", split="dev",
    )
    calls = [{"tool_name": "search_docs"}, {"tool_name": "publish_ticket"}]
    assert tool_correctness(c, calls) == 0.5


def test_tool_correctness_no_calls() -> None:
    c = BenchmarkCase(
        id="c1", family_id="x", task="t", expected_outcome="x",
        allowed_tools=("search_docs",), source_refs=(),
        reviewer="r", split="dev",
    )
    assert tool_correctness(c, []) == 0.0


def test_reliability_recovered() -> None:
    c = BenchmarkCase(
        id="c1", family_id="x", task="t", expected_outcome="x",
        allowed_tools=(), source_refs=(), reviewer="r", split="dev",
    )
    rep = reliability(c, {"recovered": True, "timed_out": False, "duplicate": False, "cancelled_clean": True})
    assert rep.recovered is True
    assert rep.timeout is False
    assert rep.duplicate_effect is False
    assert rep.cancel_clean is True


# ---- Dataset integrity ----


def test_split_counts_match_proposal(cases_dir: Path) -> None:
    dev = load_split(cases_dir / "dev", "dev")
    val = load_split(cases_dir / "val", "val")
    held = load_split(cases_dir / "held_out", "held_out")
    assert len(dev) == 18
    assert len(val) == 6
    assert len(held) == 6


def test_every_case_has_reviewer_and_split(cases_dir: Path) -> None:
    for split in ("dev", "val", "held_out"):
        for c in load_split(cases_dir / split, split):
            assert c.reviewer, f"{c.id} missing reviewer"
            assert c.split == split, f"{c.id} split mismatch"


def test_six_families_per_split(cases_dir: Path) -> None:
    for split in ("dev", "val", "held_out"):
        cases = load_split(cases_dir / split, split)
        families = {c.family_id for c in cases}
        assert families == {
            "straightforward", "multi_doc", "ambiguous",
            "missing_evidence", "stale_doc", "tool_failure",
        }, f"{split}: {families}"


def test_three_per_family_in_dev(cases_dir: Path) -> None:
    by_fam: dict[str, int] = {}
    for c in load_split(cases_dir / "dev", "dev"):
        by_fam[c.family_id] = by_fam.get(c.family_id, 0) + 1
    for fam, n in by_fam.items():
        assert n == 3, f"dev: family {fam} has {n} cases; expected 3"


def test_held_out_sha256_is_frozen(cases_dir: Path) -> None:
    expected = (cases_dir / "HELD_OUT_SHA256.txt").read_text(encoding="utf-8").strip()
    actual = held_out_sha256(cases_dir)
    assert actual == expected, f"held-out drift: expected {expected}, got {actual}"


def test_load_case_round_trip(cases_dir: Path) -> None:
    raw = json.loads((cases_dir / "dev" / "case-001.json").read_text(encoding="utf-8"))
    c = load_case(cases_dir / "dev" / "case-001.json")
    assert c.id == raw["id"]
    assert c.task == raw["task"]
    assert c.allowed_tools == tuple(raw["allowed_tools"])
    assert c.source_refs == tuple(raw["source_refs"])
