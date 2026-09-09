"""Benchmark scorers.

Per proposal:
  - task_success(case, run_outcome) -> bool
  - retrieval_recall_at_k(case, evidence_ids, k) -> float
  - tool_correctness(case, tool_calls) -> float
  - reliability(case, run_history) -> dict

The deterministic scorers never grant permission or promote labels; an
optional isolated LLM judge (in step 6) scores groundedness on a human-
reviewed subset only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    family_id: str
    task: str
    expected_outcome: str
    allowed_tools: tuple[str, ...]
    source_refs: tuple[str, ...]
    reviewer: str
    split: str  # "dev" | "val" | "held_out"


def task_success(case: BenchmarkCase, run_answer: str | None) -> bool:
    """Deterministic: case.expected_outcome is a substring of run_answer.

    For refused cases, expected_outcome is "Insufficient evidence in the corpus"
    which the agent uses as its refusal message. — so substring match works
    across the 6 families.
    """
    if not run_answer:
        return False
    needle = case.expected_outcome.strip().lower()
    if not needle:
        return False
    hay = run_answer.strip().lower()
    return needle in hay


def retrieval_recall_at_k(case: BenchmarkCase, evidence_ids: list[str], k: int = 5) -> float:
    """Relevant source IDs retrieved / gold relevant source IDs.

    Empty gold (e.g. 'missing_evidence' family) -> 1.0 by convention
    (no relevant docs to recall).
    """
    gold = set(case.source_refs)
    if not gold:
        return 1.0
    top = set(evidence_ids[:k])
    return len(gold & top) / len(gold)


def tool_correctness(case: BenchmarkCase, tool_calls: list[dict[str, Any]]) -> float:
    """Calls with correct allowed tool / scored calls.

    A call with a tool not in case.allowed_tools counts as a violation;
    correct calls count as 1.0.
    """
    if not tool_calls:
        return 0.0
    allowed = set(case.allowed_tools)
    ok = 0
    for tc in tool_calls:
        if tc.get("tool_name") in allowed:
            ok += 1
    return ok / len(tool_calls)


@dataclass(frozen=True)
class ReliabilityReport:
    recovered: bool
    timeout: bool
    duplicate_effect: bool
    cancel_clean: bool


def reliability(case: BenchmarkCase, run_history: dict[str, Any]) -> ReliabilityReport:
    """Recovery, timeout/cancel, and duplicate-effect behaviour.

    run_history keys: recovered (bool), timed_out (bool), duplicate (bool),
    cancelled_clean (bool).
    """
    return ReliabilityReport(
        recovered=bool(run_history.get("recovered", False)),
        timeout=bool(run_history.get("timed_out", False)),
        duplicate_effect=bool(run_history.get("duplicate", False)),
        cancel_clean=bool(run_history.get("cancelled_clean", False)),
    )
