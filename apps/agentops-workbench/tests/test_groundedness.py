"""TDD: groundedness.py uses three published metrics, not custom ones.

References:
  - Lin, C.-Y. (2004). ROUGE: A Package for Automatic Evaluation of
    Summaries.
  - Honovich, O., et al. (2022). TRUE: Re-evaluating the Reliability
    of Natural Language Explanations. arXiv:2205.07750.

Each metric's value matches a hand-computed expected number from
the paper's worked examples (where applicable) so the test doubles
as a numerical sanity check on the implementation.
"""
from __future__ import annotations

import pytest

from agentops_workbench import groundedness
from agentops_workbench.groundedness import (
    GroundednessScore,
    _lcs_length,
    answer_citation_precision,
    answer_citation_recall,
    answer_overall_rouge_l,
    compute_sentence_groundedness,
    rouge_l_f1,
)

# ---- ROUGE-L: LCS primitive ----


def test_lcs_length_identical_sequences() -> None:
    """LCS of two identical token sequences is the sequence length."""
    assert _lcs_length(["a", "b", "c"], ["a", "b", "c"]) == 3


def test_lcs_length_completely_disjoint_is_zero() -> None:
    assert _lcs_length(["a", "b", "c"], ["x", "y", "z"]) == 0


def test_lcs_length_partial_overlap_classic_example() -> None:
    """The textbook LCS example from Wikipedia/Hirschberg:
    "ABCDGH" vs "AEDFHR" -> 3 ("ADH")."""
    assert _lcs_length(
        ["A", "B", "C", "D", "G", "H"],
        ["A", "E", "D", "F", "H", "R"],
    ) == 3


def test_lcs_length_one_empty_is_zero() -> None:
    assert _lcs_length([], ["a", "b"]) == 0
    assert _lcs_length(["a", "b"], []) == 0
    assert _lcs_length([], []) == 0


def test_lcs_length_preserves_subsequence_order() -> None:
    """LCS is a SUBSEQUENCE not a substring — order matters but not contiguity."""
    # Tokens "a c" are a subsequence of "a b c" -> LCS = 2.
    assert _lcs_length(["a", "c"], ["a", "b", "c"]) == 2


# ---- ROUGE-L F1 ----


def test_rouge_l_f1_identical_inputs_is_one() -> None:
    f1, p, r, lcs = rouge_l_f1(
        ["postgressaver", "writes", "durable", "checkpoints"],
        ["postgressaver", "writes", "durable", "checkpoints"],
    )
    assert f1 == pytest.approx(1.0, abs=0.001)
    assert p == pytest.approx(1.0, abs=0.001)
    assert r == pytest.approx(1.0, abs=0.001)
    assert lcs == 4


def test_rouge_l_f1_disjoint_inputs_is_zero() -> None:
    f1, p, r, lcs = rouge_l_f1(
        ["mongodb", "is", "great"],
        ["postgressaver", "writes", "checkpoints"],
    )
    assert f1 == 0.0
    assert p == 0.0
    assert r == 0.0
    assert lcs == 0


def test_rouge_l_f1_paper_worked_example() -> None:
    """Reproduce Lin (2004)'s worked example to confirm we implement
    the same formula, not a custom variant.

    Hypothesis: "the cat sat on the mat"
    Reference: "the cat is on the mat"
    Tokens (lowercased, alpha only):
      hypothesis = [the, cat, sat, on, the, mat]   (length 6)
      reference  = [the, cat, is, on, the, mat]    (length 6)
    LCS = [the, cat, on, the, mat] (length 5)
    Precision = 5/6, Recall = 5/6, F1 = 2 * (5/6)^2 / (5/3) = 5/6.
    """
    f1, p, r, lcs = rouge_l_f1(
        ["the", "cat", "sat", "on", "the", "mat"],
        ["the", "cat", "is", "on", "the", "mat"],
    )
    assert lcs == 5
    assert p == pytest.approx(5 / 6, abs=0.001)
    assert r == pytest.approx(5 / 6, abs=0.001)
    assert f1 == pytest.approx(5 / 6, abs=0.001)


def test_rouge_l_f1_partial_overlap_uses_harmonic_mean() -> None:
    """When precision != recall, F1 is the harmonic mean — penalises
    imbalanced overlap."""
    # sentence has 4 tokens, evidence has 2, LCS = 2.
    # P = 2/4 = 0.5, R = 2/2 = 1.0, F1 = 2 * 0.5 * 1.0 / 1.5 = 0.667.
    f1, p, r, _ = rouge_l_f1(
        ["a", "b", "c", "d"],
        ["a", "b"],
    )
    assert p == pytest.approx(0.5, abs=0.001)
    assert r == pytest.approx(1.0, abs=0.001)
    assert f1 == pytest.approx(2 / 3, abs=0.001)


def test_rouge_l_f1_one_empty_input_is_zero() -> None:
    """Empty input -> 0 (no content to score)."""
    assert rouge_l_f1([], ["a", "b"])[0] == 0.0
    assert rouge_l_f1(["a", "b"], [])[0] == 0.0
    assert rouge_l_f1([], [])[0] == 0.0


# ---- Citation Recall + Precision (Honovich et al., 2022) ----


def test_citation_recall_one_of_two_sentences_cited_is_half() -> None:
    scores = [
        GroundednessScore(sentence="cited [ref-a]", cited_refs=["ref-a"]),
        GroundednessScore(sentence="uncited", cited_refs=[]),
    ]
    assert answer_citation_recall(scores) == pytest.approx(0.5, abs=0.001)


def test_citation_recall_unresolved_citation_does_not_count() -> None:
    """Honovich et al.: only citations that resolve to real evidence
    count toward recall. A sentence with only fabricated refs is
    treated as uncited."""
    scores = [
        GroundednessScore(
            sentence="fabricated [ref-bogus]",
            cited_refs=[],
            unresolved_refs=["ref-bogus"],
        ),
    ]
    assert answer_citation_recall(scores) == 0.0


def test_citation_recall_empty_answer_is_zero() -> None:
    assert answer_citation_recall([]) == 0.0


def test_citation_precision_two_of_three_cited_refs_resolve() -> None:
    scores = [
        GroundednessScore(
            sentence="[ref-a] [ref-b] [ref-bogus]",
            cited_refs=["ref-a", "ref-b"],
            unresolved_refs=["ref-bogus"],
        ),
    ]
    assert answer_citation_precision(scores) == pytest.approx(2 / 3, abs=0.001)


def test_citation_precision_aggregates_across_sentences() -> None:
    """Two sentences: 2 valid + 1 invalid out of 3 total -> 2/3."""
    scores = [
        GroundednessScore(
            sentence="[ref-a]",
            cited_refs=["ref-a"],
            unresolved_refs=[],
        ),
        GroundednessScore(
            sentence="[ref-b] [ref-bogus]",
            cited_refs=["ref-b"],
            unresolved_refs=["ref-bogus"],
        ),
    ]
    assert answer_citation_precision(scores) == pytest.approx(2 / 3, abs=0.001)


def test_citation_precision_no_emitted_citations_is_zero() -> None:
    scores = [GroundednessScore(sentence="no markers", cited_refs=[])]
    assert answer_citation_precision(scores) == 0.0


# ---- Overall ROUGE-L aggregation ----


def test_answer_overall_rouge_l_macro_average() -> None:
    """Macro-average: unweighted mean across sentences."""
    scores = [
        GroundednessScore(sentence="a", rouge_l_f1=0.5),
        GroundednessScore(sentence="b", rouge_l_f1=0.9),
    ]
    assert answer_overall_rouge_l(scores) == pytest.approx(0.7, abs=0.001)


# ---- compute_sentence_groundedness ----


def test_perfect_rouge_l_f1_when_sentence_matches_evidence() -> None:
    evidence_map = {
        "ref-a": "the cat sat on the mat",
    }
    sentence = "the cat sat on the mat [ref-a]"
    gs = compute_sentence_groundedness(sentence, ["ref-a"], evidence_map)
    assert isinstance(gs, GroundednessScore)
    assert gs.rouge_l_f1 == pytest.approx(1.0, abs=0.001)
    assert gs.rouge_l_precision == pytest.approx(1.0, abs=0.001)
    assert gs.rouge_l_recall == pytest.approx(1.0, abs=0.001)
    assert gs.cited_refs == ["ref-a"]
    assert gs.unresolved_refs == []


def test_zero_rouge_l_f1_for_fully_disjoint_sentence() -> None:
    """Tokens of the sentence and evidence share nothing — LCS = 0.
    Use a sentence whose tokens don't overlap at all with the
    evidence (no common stopword like 'the' that could inflate LCS)."""
    evidence_map = {
        "ref-a": "PostgresSaver writes durable checkpoints",
    }
    sentence = "MongoDB clusters horizontally across shards [ref-a]"
    gs = compute_sentence_groundedness(sentence, ["ref-a"], evidence_map)
    assert gs.lcs_length == 0
    assert gs.rouge_l_f1 == pytest.approx(0.0, abs=0.001)
    assert gs.rouge_l_precision == 0.0
    assert gs.rouge_l_recall == 0.0


def test_unknown_citation_ref_goes_to_unresolved_not_score() -> None:
    """An LLM-hallucinated [ref-x] is reported but does NOT contribute
    to evidence tokens, so it does NOT inflate the ROUGE-L score."""
    evidence_map = {"ref-a": "the cat is on the mat"}
    gs = compute_sentence_groundedness(
        "the cat is on the mat",
        ["ref-a", "ref-nonexistent"],
        evidence_map,
    )
    assert gs.rouge_l_f1 == pytest.approx(1.0, abs=0.001)
    assert "ref-nonexistent" in gs.unresolved_refs


def test_empty_citation_list_scores_zero_evidence_overlap() -> None:
    """A sentence with no citations has no evidence to compare against,
    so ROUGE-L is 0.0 (not 1.0)."""
    evidence_map = {"ref-a": "any text"}
    gs = compute_sentence_groundedness(
        "MongoDB is the best NoSQL store",
        [],
        evidence_map,
    )
    assert gs.rouge_l_f1 == 0.0
    assert gs.cited_refs == []


# ---- end-to-end: split answer -> per-sentence scores ----


def test_groundedness_for_answer_returns_per_sentence_list() -> None:
    """The helper used by /v1/wiki/qa splits an LLM answer and
    scores each sentence with ROUGE-L F1."""
    answer = (
        "The cat sat on the mat. [ref-a] "
        "MongoDB is unrelated. [ref-b]"
    )
    evidence_map = {
        "ref-a": "The cat sat on the mat",
        "ref-b": "MemorySaver resets on restart for tests",
    }
    scores = groundedness.groundedness_for_answer(answer, evidence_map)
    assert len(scores) == 2, f"expected 2 sentences, got {len(scores)}: {[s.sentence for s in scores]}"
    # First sentence: identical to ref-a -> F1 = 1.0.
    assert scores[0].rouge_l_f1 == pytest.approx(1.0, abs=0.001)
    # Second sentence: completely disjoint from ref-b -> F1 = 0.0.
    assert scores[1].rouge_l_f1 == pytest.approx(0.0, abs=0.001)


def test_answer_level_metrics_aggregate_correctly() -> None:
    """The end-to-end API returns three answer-level numbers; we
    verify they aggregate as documented."""
    answer = (
        "The cat sat on the mat. [ref-a] "
        "MongoDB is unrelated. [ref-bogus]"   # fabricated citation
    )
    evidence_map = {
        "ref-a": "The cat sat on the mat",
    }
    scores = groundedness.groundedness_for_answer(answer, evidence_map)
    # Citation Recall: 1 of 2 sentences has a valid citation -> 0.5.
    assert answer_citation_recall(scores) == pytest.approx(0.5, abs=0.001)
    # Citation Precision: 1 valid (ref-a) + 1 invalid (ref-bogus)
    # out of 2 emitted -> 0.5.
    assert answer_citation_precision(scores) == pytest.approx(0.5, abs=0.001)
    # Overall ROUGE-L F1: macro-average across sentences.
    assert answer_overall_rouge_l(scores) == pytest.approx(0.5, abs=0.001)
