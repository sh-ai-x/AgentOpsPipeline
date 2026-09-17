"""ADR-0010 step 8: retrieval-quality metrics for comparing WikiRagAdapter
modes. Pure Python, hand-computed expectations -- separate from
`benchmark/scorers.py::retrieval_recall_at_k`, which is typed to the
answer-level 30-case `BenchmarkCase` benchmark and is NOT modified here.
"""
from __future__ import annotations

import math

import pytest

from agentops_workbench.benchmark.retrieval_metrics import (
    collapse_to_parents,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

# A 5-item ranking used across several metrics below, with two gold docs.
_RANKED = ["c", "a", "x", "b", "y"]
_GOLD = {"a", "b"}


def test_hit_rate_at_k_true_when_any_gold_in_top_k() -> None:
    assert hit_rate_at_k(_GOLD, _RANKED, k=1) == 0.0  # "c" alone, no gold
    assert hit_rate_at_k(_GOLD, _RANKED, k=2) == 1.0  # "a" enters at rank 2


def test_hit_rate_at_k_empty_gold_is_perfect_by_convention() -> None:
    assert hit_rate_at_k(set(), _RANKED, k=3) == 1.0


def test_recall_at_k_counts_fraction_of_gold_found() -> None:
    assert recall_at_k(_GOLD, _RANKED, k=2) == pytest.approx(0.5)   # found "a" only
    assert recall_at_k(_GOLD, _RANKED, k=4) == pytest.approx(1.0)   # found "a" and "b"


def test_recall_at_k_empty_gold_is_perfect_by_convention() -> None:
    assert recall_at_k(set(), _RANKED, k=3) == 1.0


def test_precision_at_k_counts_fraction_of_returned_that_are_gold() -> None:
    assert precision_at_k(_GOLD, _RANKED, k=4) == pytest.approx(2 / 4)
    assert precision_at_k(_GOLD, _RANKED, k=1) == pytest.approx(0.0)


def test_precision_at_k_empty_gold_convention() -> None:
    # Empty gold: perfect (1.0) iff nothing was returned; 0.0 if anything was.
    assert precision_at_k(set(), [], k=5) == 1.0
    assert precision_at_k(set(), _RANKED, k=5) == 0.0


def test_precision_at_k_handles_k_larger_than_the_ranking() -> None:
    assert precision_at_k(_GOLD, ["a"], k=10) == pytest.approx(1.0)


def test_mrr_is_reciprocal_rank_of_first_gold_hit() -> None:
    # "a" is at index 1 (0-based) -> rank 2 -> MRR = 1/2.
    assert mrr(_GOLD, _RANKED) == pytest.approx(0.5)


def test_mrr_is_zero_when_no_gold_present() -> None:
    assert mrr({"zzz"}, _RANKED) == 0.0


def test_ndcg_at_k_matches_a_hand_worked_example() -> None:
    # Graded relevance: "a" highly relevant (2), "b" partially (1), rest 0.
    grades = {"a": 2, "b": 1}
    ranked = ["c", "a", "b"]  # a at rank 2, b at rank 3 (1-indexed for the formula)
    # DCG = (2^0-1)/log2(2) + (2^2-1)/log2(3) + (2^1-1)/log2(4)
    dcg = (2**0 - 1) / math.log2(2) + (2**2 - 1) / math.log2(3) + (2**1 - 1) / math.log2(4)
    # Ideal order: a (grade 2) then b (grade 1).
    idcg = (2**2 - 1) / math.log2(2) + (2**1 - 1) / math.log2(3)
    expected = dcg / idcg
    assert ndcg_at_k(grades, ranked, k=3) == pytest.approx(expected)


def test_ndcg_at_k_perfect_ranking_is_one() -> None:
    grades = {"a": 2, "b": 1}
    assert ndcg_at_k(grades, ["a", "b", "x"], k=3) == pytest.approx(1.0)


def test_ndcg_at_k_all_zero_grades_is_a_trivial_perfect_score() -> None:
    """The no_answer family: nothing is relevant, so a query returning
    nothing (or anything) scores 1.0 -- there is no way to be "wrong"."""
    assert ndcg_at_k({}, ["x", "y"], k=5) == 1.0
    assert ndcg_at_k({"x": 0, "y": 0}, [], k=5) == 1.0


def test_collapse_to_parents_dedupes_chunk_hits_keeping_first_occurrence() -> None:
    ranked = ["doc1#c0", "doc1#c3", "doc2#c1", "doc1#c1", "doc3"]
    assert collapse_to_parents(ranked) == ["doc1", "doc2", "doc3"]


def test_collapse_to_parents_is_a_no_op_for_whole_file_ref_ids() -> None:
    assert collapse_to_parents(["a", "b", "c"]) == ["a", "b", "c"]
