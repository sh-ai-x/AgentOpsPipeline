"""Academic-grounded attribution metrics for LLM answers.

Phase 9 AC3 requires every LLM-generated claim to carry a
groundedness score drawn from the established metrics literature,
NOT custom-defined ones. This module implements three:

  - **ROUGE-L F1** (Lin, 2004 — "ROUGE: A Package for Automatic
    Evaluation of Summaries"). Sentence-vs-evidence F-measure over
    the longest common subsequence (LCS) of token sequences.
    Pure Python, no dependencies, well-cited baseline.

  - **Citation Recall** (Honovich et al., 2022 — "TRUE: Re-evaluating
    the Reliability of Natural Language Explanations"). Fraction
    of sentences that carry at least one citation marker.
    Independent of evidence content — measures *whether* the LLM
    attributed, not *whether* it attributed correctly.

  - **Citation Precision** (Honovich et al., 2022). Fraction of
    emitted `[ref-x]` markers that resolve to a real evidence
    block. Catches fabricated citations.

Together these three give a reviewer:
  - "Did the LLM cite its claims?"  -> Citation Recall
  - "Did the LLM cite real refs?"    -> Citation Precision
  - "How closely do the claims match the cited evidence?" -> ROUGE-L F1

References:
  - Lin, C.-Y. (2004). ROUGE: A Package for Automatic Evaluation of
    Summaries. In Text Summarization Branches Out, ACL workshop.
  - Honovich, O., et al. (2022). TRUE: Re-evaluating the Reliability
    of Natural Language Explanations. arXiv:2205.07750.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from .wiki_corpus import extract_citation_refs, split_sentences, tokenize

# Strip `[ref-x]` markers from a sentence before tokenizing for the
# coverage calculation. Without this, citation metadata would inflate
# the sentence's token count and lower ROUGE-L artificially.
_CITATION_STRIP_RE = re.compile(r"\[[A-Za-z0-9_.~-]+\]")


@dataclass(frozen=True)
class GroundednessScore:
    """Per-sentence attribution result with three published metrics.

    Attributes:
      sentence:         Original sentence text (with citations kept).
      cited_refs:       Citations that resolve to real evidence blocks.
      unresolved_refs:  Citations the LLM emitted but which have no
                        matching evidence — fabricated citations.
      rouge_l_f1:       ROUGE-L F1 (Lin, 2004) between the sentence
                        and the union of cited evidence.
      rouge_l_precision: ROUGE-L precision = LCS / |sentence tokens|.
      rouge_l_recall:    ROUGE-L recall    = LCS / |evidence tokens|.
    """

    sentence: str
    cited_refs: list[str] = field(default_factory=list)
    unresolved_refs: list[str] = field(default_factory=list)
    rouge_l_f1: float = 0.0
    rouge_l_precision: float = 0.0
    rouge_l_recall: float = 0.0
    sentence_tokens: int = 0
    evidence_tokens: int = 0
    lcs_length: int = 0

    def to_dict(self) -> dict:
        return {
            "sentence": self.sentence,
            "cited_refs": list(self.cited_refs),
            "unresolved_refs": list(self.unresolved_refs),
            "rouge_l_f1": round(self.rouge_l_f1, 4),
            "rouge_l_precision": round(self.rouge_l_precision, 4),
            "rouge_l_recall": round(self.rouge_l_recall, 4),
            "sentence_tokens": self.sentence_tokens,
            "evidence_tokens": self.evidence_tokens,
            "lcs_length": self.lcs_length,
        }


# ---- ROUGE-L (Lin, 2004) ----


def _lcs_length(a: Sequence[str], b: Sequence[str]) -> int:
    """Length of the longest common subsequence of two token sequences.

    Standard O(|a| * |b|) dynamic-programming formulation. Empty
    inputs return 0; equal sequences return len(sequence).
    """
    if not a or not b:
        return 0
    # Use a 1-D rolling array to keep memory bounded.
    prev = [0] * (len(b) + 1)
    curr = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, prev
    return prev[len(b)]


def rouge_l_f1(
    sentence_tokens: Sequence[str],
    evidence_tokens: Sequence[str],
) -> tuple[float, float, float, int]:
    """Compute ROUGE-L F1 between sentence and evidence token sequences.

    Returns (f1, precision, recall, lcs_length). Implements the
    Lin (2004) formulation:
      P = LCS / |sentence|
      R = LCS / |evidence|
      F1 = 2 * P * R / (P + R)

    Edge cases match the paper's convention: if both inputs are
    empty, F1 = 0.0 (no content to score). If one is empty but the
    other isn't, F1 = 0.0 (zero overlap by definition).
    """
    lcs = _lcs_length(sentence_tokens, evidence_tokens)
    s_len = len(sentence_tokens)
    e_len = len(evidence_tokens)
    if lcs == 0 or s_len == 0 or e_len == 0:
        return 0.0, 0.0, 0.0, lcs
    precision = lcs / s_len
    recall = lcs / e_len
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return f1, precision, recall, lcs


# ---- Citation metrics (Honovich et al., 2022) ----


def answer_citation_recall(scores: list[GroundednessScore]) -> float:
    """Fraction of sentences carrying at least one *valid* citation.

    Honovich et al. (2022) define citation recall as the proportion
    of sentences with a citation that resolves to a real evidence
    block. We follow that interpretation — a sentence citing only
    an unresolved `[ref-x]` doesn't count as attributed.
    """
    if not scores:
        return 0.0
    cited = sum(1 for s in scores if s.cited_refs)
    return cited / len(scores)


def answer_citation_precision(
    scores: list[GroundednessScore],
) -> float:
    """Fraction of emitted `[ref-x]` markers that resolve to evidence.

    Honovich et al. (2022). If the LLM emits `[ref-a] [ref-bogus]`
    on a sentence and only `ref-a` resolves, the per-sentence
    precision is 1/2. We aggregate as a weighted mean by citation
    count so a sentence with zero citations contributes 0 to both
    numerator and denominator (not "perfect precision").
    """
    total_emitted = 0
    total_resolved = 0
    for s in scores:
        emitted = len(s.cited_refs) + len(s.unresolved_refs)
        total_emitted += emitted
        total_resolved += len(s.cited_refs)
    if total_emitted == 0:
        return 0.0
    return total_resolved / total_emitted


def answer_overall_rouge_l(scores: list[GroundednessScore]) -> float:
    """Macro-average ROUGE-L F1 across sentences.

    Macro-average (unweighted mean per sentence) is what Lin (2004)
    reports for multi-sentence evaluation; micro-average would
    weight by sentence length and obscure short-sentence behaviour.
    """
    if not scores:
        return 0.0
    return sum(s.rouge_l_f1 for s in scores) / len(scores)


# ---- Per-sentence scoring ----


def _strip_citations(text: str) -> str:
    """Remove `[ref-x]` markers so the sentence tokenization reflects
    only the claim, not the citation metadata."""
    return _CITATION_STRIP_RE.sub("", text)


def compute_sentence_groundedness(
    sentence: str,
    cited_refs: list[str],
    evidence_map: dict[str, str],
) -> GroundednessScore:
    """Score one sentence against the union of its cited evidence.

    Splits the cited refs into resolved (key exists in evidence_map)
    and unresolved (LLM hallucinated). Computes ROUGE-L F1 between
    the sentence (citations stripped) and the union of cited evidence.
    """
    claim = _strip_citations(sentence)
    sent_tokens = list(tokenize(claim))
    evidence_tokens: list[str] = []
    resolved: list[str] = []
    unresolved: list[str] = []
    for rid in cited_refs:
        text = evidence_map.get(rid)
        if text is None:
            unresolved.append(rid)
            continue
        resolved.append(rid)
        evidence_tokens.extend(tokenize(text))
    f1, precision, recall, lcs = rouge_l_f1(sent_tokens, evidence_tokens)
    return GroundednessScore(
        sentence=sentence,
        cited_refs=resolved,
        unresolved_refs=unresolved,
        rouge_l_f1=f1,
        rouge_l_precision=precision,
        rouge_l_recall=recall,
        sentence_tokens=len(sent_tokens),
        evidence_tokens=len(evidence_tokens),
        lcs_length=lcs,
    )


def groundedness_for_answer(
    answer: str,
    evidence_map: dict[str, str],
) -> list[GroundednessScore]:
    """Split `answer` into sentences and score each with ROUGE-L F1.

    Citations are extracted per-sentence. `answer_citation_recall`
    and `answer_citation_precision` aggregate over the returned list.
    """
    sents = split_sentences(answer)
    scores: list[GroundednessScore] = []
    for sent in sents:
        cited = extract_citation_refs(sent)
        scores.append(compute_sentence_groundedness(sent, cited, evidence_map))
    return scores
