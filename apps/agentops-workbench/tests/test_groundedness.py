"""TDD: groundedness.py sentence-coverage scorer + per-sentence attribution.

Phase 9 AC3 uses sentence-token recall (not Jaccard) as the proxy for
"how much of this claim is grounded?". Rationale: the user-facing
question is "how much of THIS claim is hallucinated?" — the natural
inverse is sentence-token coverage by cited evidence.
"""
from __future__ import annotations

import pytest

from agentops_workbench import groundedness
from agentops_workbench.groundedness import (
    GroundednessScore,
    compute_sentence_groundedness,
    jaccard,
    sentence_coverage,
)

# ---- Pure jaccard (still used for completeness in some UI badges) ----


def test_jaccard_identical_sets_is_one() -> None:
    assert jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0


def test_jaccard_disjoint_sets_is_zero() -> None:
    assert jaccard({"a", "b"}, {"x", "y"}) == 0.0


def test_jaccard_partial_overlap() -> None:
    # |A∩B| = 2 (a,b), |A∪B| = 4 (a,b,c,x) -> 0.5
    assert jaccard({"a", "b", "c"}, {"a", "b", "x"}) == 0.5


def test_jaccard_empty_both_is_zero() -> None:
    # By convention, empty/empty has no information -> 0.0 (NOT 1.0).
    assert jaccard(set(), set()) == 0.0


def test_jaccard_one_empty_other_nonempty_is_zero() -> None:
    assert jaccard(set(), {"a"}) == 0.0
    assert jaccard({"a"}, set()) == 0.0


# ---- sentence_coverage (the AC3 metric) ----


def test_sentence_coverage_full_overlap_is_one() -> None:
    assert sentence_coverage({"a", "b", "c"}, {"a", "b", "c", "d"}) == 1.0


def test_sentence_coverage_no_overlap_is_zero() -> None:
    assert sentence_coverage({"a", "b"}, {"x", "y"}) == 0.0


def test_sentence_coverage_partial_fraction() -> None:
    # 3 sentence tokens, 2 in evidence -> 2/3 ≈ 0.667
    assert sentence_coverage({"a", "b", "c"}, {"a", "b", "x"}) == pytest.approx(2 / 3)


def test_sentence_coverage_empty_sentence_is_zero() -> None:
    # Empty sentence -> no claim -> 0.0 (not "perfect").
    assert sentence_coverage(set(), {"a"}) == 0.0


def test_sentence_coverage_empty_evidence_nonempty_sentence_is_zero() -> None:
    assert sentence_coverage({"a"}, set()) == 0.0


# ---- compute_sentence_groundedness ----


def test_perfect_groundedness_when_sentence_tokens_all_in_evidence() -> None:
    """A sentence whose every token appears in cited evidence scores 1.0."""
    evidence_map = {
        "ref-a": "PostgresSaver writes durable checkpoints to a Postgres table.",
    }
    # Sentence tokens (lower-cased alphanumeric): postgressaver, writes,
    # durable, checkpoints. All appear in evidence -> 1.0.
    sentence = "PostgresSaver writes durable checkpoints."
    gs = compute_sentence_groundedness(sentence, ["ref-a"], evidence_map)
    assert isinstance(gs, GroundednessScore)
    assert gs.score == pytest.approx(1.0, abs=0.001)
    assert gs.cited_refs == ["ref-a"]


def test_zero_groundedness_when_no_overlap() -> None:
    evidence_map = {
        "ref-a": "PostgresSaver writes durable checkpoints.",
    }
    # Sentence tokens: mongodb, is, the, best, nosql, store. None in evidence.
    sentence = "MongoDB is the best NoSQL store."
    gs = compute_sentence_groundedness(sentence, ["ref-a"], evidence_map)
    assert gs.score == pytest.approx(0.0, abs=0.001)


def test_multi_citation_unions_evidence_tokens() -> None:
    """When a sentence cites [a] and [b], the evidence union is the
    combined token set of both refs."""
    evidence_map = {
        "ref-a": "PostgresSaver writes durable checkpoints.",
        "ref-b": "MemorySaver resets on restart, suitable for tests.",
    }
    # Sentence tokens: postgressaver, writes, durable, checkpoints, suitable,
    # for, tests. All covered by union of refs -> 1.0.
    sentence = "PostgresSaver writes durable checkpoints, suitable for tests."
    gs = compute_sentence_groundedness(sentence, ["ref-a", "ref-b"], evidence_map)
    assert gs.score == pytest.approx(1.0, abs=0.001)


def test_unknown_citation_ref_is_ignored_silently() -> None:
    """An LLM may hallucinate a [ref_id]; we silently drop unknown refs
    rather than crash — the score reflects only the resolvable citations."""
    evidence_map = {
        "ref-a": "PostgresSaver writes durable checkpoints.",
    }
    gs = compute_sentence_groundedness(
        "PostgresSaver writes durable checkpoints.",
        ["ref-a", "ref-nonexistent"],
        evidence_map,
    )
    assert gs.score == pytest.approx(1.0, abs=0.001)
    # The unresolved ref is reported (for UI diagnostics) but excluded
    # from the score computation.
    assert "ref-nonexistent" in gs.unresolved_refs


def test_empty_citation_list_scores_zero() -> None:
    """A sentence with NO [ref_id] citations is ungrounded by definition."""
    evidence_map = {"ref-a": "any text"}
    gs = compute_sentence_groundedness(
        "PostgresSaver writes durable checkpoints.",
        [],
        evidence_map,
    )
    assert gs.score == 0.0
    assert gs.cited_refs == []


def test_partial_groundedness_score_is_fraction() -> None:
    """3 of 5 sentence tokens in evidence -> 3/5 = 0.6."""
    evidence_map = {
        "ref-a": "PostgresSaver checkpoints are durable.",
    }
    # Sentence tokens: postgressaver, checkpoints, are, durable, and, amazing (6)
    # Evidence tokens: postgressaver, checkpoints, are, durable (4)
    # Overlap: 4, sentence size: 6 -> 4/6 ≈ 0.667
    sentence = "PostgresSaver checkpoints are durable and amazing."
    gs = compute_sentence_groundedness(sentence, ["ref-a"], evidence_map)
    expected = 4 / 6
    assert gs.score == pytest.approx(expected, abs=0.01)


# ---- end-to-end: sentence list -> per-sentence scores ----


def test_groundedness_for_answer_returns_per_sentence_list() -> None:
    """The helper used by /v1/wiki/qa must split an LLM answer into
    sentences and return one GroundednessScore per sentence.

    Sentence boundaries respect citations at sentence-end (e.g.
    "Foo. [ref-x] Bar.") so each citation stays attached to its claim.
    """
    answer = (
        "PostgresSaver writes durable checkpoints. [ref-a] "
        "MongoDB is unrelated. [ref-b]"
    )
    evidence_map = {
        "ref-a": "PostgresSaver writes durable checkpoints to Postgres.",
        "ref-b": "MemorySaver resets on restart for tests.",
    }
    scores = groundedness.groundedness_for_answer(answer, evidence_map)
    assert len(scores) == 2, f"expected 2 sentences, got {len(scores)}: {[s.sentence for s in scores]}"
    # First sentence: full coverage (postgressaver, writes, durable,
    # checkpoints all in ref-a).
    assert scores[0].score == pytest.approx(1.0, abs=0.01)
    # Second sentence: zero overlap with ref-b (mongodb vs memorysaver).
    assert scores[1].score == pytest.approx(0.0, abs=0.01)
