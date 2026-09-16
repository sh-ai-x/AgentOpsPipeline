"""TDD: faithfulness metric (Maynez et al., 2020).

Faithfulness = fraction of atomic facts in the answer that are
supported by the cited evidence. Distinct from Citation Precision,
which only checks whether `[ref-x]` markers resolve to real evidence
-- it doesn't catch a model that cites `[1]` correctly but slips an
unsupported claim into the same sentence.

The published formulation tokenizes the answer into atomic facts
(usually sentences or clause-level claims), then for each fact asks:
"is this entailed by the source?" Maynez et al. used human raters;
later work (FactCC, 2020; QAGS, 2021) automated this with NLI
models. We don't have an NLI model dependency, so we use the
dependency-light proxy that's standard in the same family of work:

  faithfulness = (atomic facts in answer whose tokens appear in
                  cited evidence) / (total atomic facts in answer)

This is the "lexical entailment proxy" referenced in the Maynez 2020
follow-up literature (Goodrich et al., 2019 -- "Assessing the
Factual Accuracy of Generated Claims"). It shares the limitation of
ROUGE-style metrics -- it doesn't catch paraphrastic hallucination --
but it's a published and accepted proxy on the same family, no model
dependency, and surfaces "this sentence had nothing to do with the
evidence at all" which is the most operationally useful failure mode.

Used in two places:
  - per-turn badge next to ROUGE-L F1 / Citation Recall / Precision
  - per-trailing-window average in the dashboard's hallucination panel
"""
from __future__ import annotations

import pytest

from agentops_workbench.groundedness import (
    GroundednessScore,
    answer_faithfulness,
    extract_atomic_facts,
    fact_supported,
)


def test_fact_supported_when_every_token_appears_in_evidence() -> None:
    evidence_map = {
        "ref-a": "LangGraph checkpointing persists graph state via Postgres.",
    }
    # Every token in the claim is also in the evidence -> supported.
    assert fact_supported(
        "LangGraph checkpointing via Postgres.",
        evidence_map,
        cited_refs=["ref-a"],
    ) is True


def test_fact_unsupported_when_tokens_absent_from_evidence() -> None:
    evidence_map = {
        "ref-a": "LangGraph checkpointing persists graph state.",
    }
    # "MongoDB" never appears in the evidence -> unsupported.
    assert fact_supported(
        "LangGraph uses MongoDB for storage.",
        evidence_map,
        cited_refs=["ref-a"],
    ) is False


def test_fact_unsupported_when_no_evidence_at_all() -> None:
    """A claim with no cited refs has nothing to be supported by."""
    assert fact_supported(
        "Anything at all.",
        evidence_map={},
        cited_refs=[],
    ) is False


def test_fact_supported_uses_union_of_cited_evidence() -> None:
    """Two citations, each contributing some tokens, both required
    to support the full claim."""
    evidence_map = {
        "ref-a": "LangGraph uses state machines.",
        "ref-b": "checkpointing persists state across crashes.",
    }
    assert fact_supported(
        "LangGraph uses state machines; checkpointing persists "
        "state across crashes.",
        evidence_map,
        cited_refs=["ref-a", "ref-b"],
    ) is True


def test_fact_supported_ignores_unresolved_refs() -> None:
    """A citation that doesn't resolve to real evidence must not
    contribute tokens to the support check -- that would let the LLM
    'support' any claim by inventing an `[ref-x]` marker."""
    evidence_map = {
        "ref-a": "LangGraph checkpointing persists graph state.",
    }
    # "ref-bogus" isn't in evidence_map; tokens from the evidence for
    # "ref-bogus" (i.e. "") should not contribute. Claim contains "uses
    # MongoDB" which is NOT in the only real evidence -> unsupported.
    assert fact_supported(
        "LangGraph uses MongoDB. [ref-bogus]",
        evidence_map,
        cited_refs=["ref-bogus"],
    ) is False


def test_extract_atomic_facts_splits_on_sentence_boundaries() -> None:
    answer = "First claim. Second claim. Third claim."
    facts = extract_atomic_facts(answer)
    assert len(facts) == 3
    assert all(c.strip() for c in facts)


def test_extract_atomic_facts_strips_citation_markers_from_facts() -> None:
    """Citation metadata shouldn't be a fact of its own."""
    answer = "The runtime serializes state. [ref-a] State survives crashes."
    facts = extract_atomic_facts(answer)
    # Two facts; neither contains "[ref-a]" (citation metadata is
    # stripped so scoring only sees the actual claim text).
    joined = " ".join(facts)
    assert "[ref-a]" not in joined
    assert "runtime serializes" in joined
    assert "survives crashes" in joined


def test_extract_atomic_facts_handles_single_sentence() -> None:
    assert len(extract_atomic_facts("Just one sentence here.")) == 1


def test_extract_atomic_facts_returns_empty_for_empty_input() -> None:
    assert extract_atomic_facts("") == []
    assert extract_atomic_facts("   ") == []


def test_answer_faithfulness_one_supported_one_unsupported() -> None:
    """The headline behavior: an answer with one supported + one
    unsupported fact should score ~0.5 on faithfulness."""
    scores = [
        # Sentence 1: supported (every token in evidence).
        GroundednessScore(
            sentence="LangGraph checkpointing persists state.",
            cited_refs=["ref-a"],
            unresolved_refs=[],
            rouge_l_f1=1.0,
        ),
        # Sentence 2: cites a bogus ref -> no evidence -> unsupported.
        GroundednessScore(
            sentence="MongoDB clusters horizontally.",
            cited_refs=[],
            unresolved_refs=["ref-bogus"],
            rouge_l_f1=0.0,
        ),
    ]
    evidence_map = {"ref-a": "LangGraph checkpointing persists state."}
    assert answer_faithfulness(scores, evidence_map) == pytest.approx(0.5)


def test_answer_faithfulness_all_supported_returns_one() -> None:
    scores = [
        GroundednessScore(
            sentence="LangGraph uses state machines.",
            cited_refs=["ref-a"],
            unresolved_refs=[],
            rouge_l_f1=1.0,
        ),
        GroundednessScore(
            sentence="Checkpointing persists state.",
            cited_refs=["ref-b"],
            unresolved_refs=[],
            rouge_l_f1=1.0,
        ),
    ]
    evidence_map = {
        "ref-a": "LangGraph uses state machines.",
        "ref-b": "Checkpointing persists state.",
    }
    assert answer_faithfulness(scores, evidence_map) == pytest.approx(1.0)


def test_answer_faithfulness_empty_evidence_returns_zero() -> None:
    scores = [
        GroundednessScore(sentence="Anything."),
    ]
    assert answer_faithfulness(scores, {}) == 0.0


def test_answer_faithfulness_zero_atoms_returns_zero() -> None:
    """Edge case: every sentence tokenized to nothing (e.g. pure-
    punctuation response). Faithfulness is undefined; return 0, not
    NaN/divide-by-zero."""
    scores = [
        GroundednessScore(sentence="..."),
    ]
    assert answer_faithfulness(scores, {"ref-a": "anything"}) == 0.0


def test_answer_faithfulness_no_cited_refs_returns_zero() -> None:
    """A sentence with no citations and no resolved refs contributes
    0 atoms to the denominator AND 0 to the supported count -- the
    same convention as Citation Precision (Honovich 2022)."""
    scores = [
        GroundednessScore(
            sentence="Free-floating unsupported claim.",
            cited_refs=[],
            unresolved_refs=[],
            rouge_l_f1=0.0,
        ),
    ]
    assert answer_faithfulness(scores, {"ref-a": "anything"}) == 0.0


# ---- Faithfulness wired into the per-turn badge ----


def test_qa_response_includes_faithfulness_field():
    """The QaResponse Pydantic model must grow a `faithfulness` field so
    the per-turn badge can read it."""
    from agentops_workbench.api.server import QaResponse
    fields = QaResponse.model_fields
    assert "faithfulness" in fields, (
        "QaResponse must carry a per-turn faithfulness score for the "
        "frontend badge. QaResponse fields: " + ", ".join(fields.keys())
    )


def test_wiki_chat_graph_returns_faithfulness_on_chat_turn():
    """graph/wiki_chat.py::run_wiki_chat returns a ChatTurn carrying
    `faithfulness` so the frontend can render the badge without
    recomputing anything."""
    from agentops_workbench.graph.wiki_chat import ChatTurn
    fields = ChatTurn.__dataclass_fields__
    assert "faithfulness" in fields


# ---- Faithfulness aggregated into the dashboard's hallucination panel ----


def test_groundedness_recorder_records_faithfulness():
    """The rolling-window GroundednessRecorder must gain a `record_faithfulness`
    path (or its existing record() must accept a faithfulness kwarg) so
    the wiki_qa endpoint can drop a sample per call."""
    from agentops_workbench.wiki_metrics import GroundednessRecorder
    r = GroundednessRecorder(window=10)
    r.reset_for_tests()
    # The existing record() signature takes a GroundednessSample; the
    # simplest path that preserves the API is to add a `faithfulness`
    # field to GroundednessSample so callers populate it.
    from agentops_workbench.wiki_metrics import GroundednessSample
    fields = GroundednessSample.__dataclass_fields__
    assert "faithfulness" in fields


def test_groundedness_metrics_stats_includes_faithfulness_avg():
    """The dashboard's `groundedness` payload must expose
    `faithfulness_avg` so the frontend can render a fourth bar."""
    from agentops_workbench.wiki_metrics import GroundednessRecorder
    r = GroundednessRecorder(window=10)
    r.reset_for_tests()
    # No samples -> 0.0 (well-defined, no divide-by-zero).
    stats = r.stats()
    assert "faithfulness_avg" in stats
    assert stats["faithfulness_avg"] == 0.0
