"""Per-sentence groundedness scoring for LLM answers.

Phase 9 AC3 requires every LLM-generated claim to carry a groundedness
score — a number in [0, 1] measuring how much of the sentence's
content is supported by the evidence the LLM cited.

We use the simplest defensible proxy: sentence-token recall over the
union of cited evidence (i.e. fraction of the sentence's tokens that
appear in cited evidence). No NLI model, no embedding, no calibration —
the scorer is fully deterministic and dependency-free.

Intuition: a sentence scoring 1.0 has every token covered by cited
evidence; 0.0 has zero overlap and is flagged as unsourced. We chose
recall (not precision, not Jaccard) because the *user-facing*
question is "how much of THIS claim is hallucinated?" — the natural
inverse is "how much of it is grounded?" = sentence-token recall.

Citation tokens are stripped from the sentence before scoring: a
sentence like "PostgresSaver writes durable checkpoints. [ref-a]"
has the `[ref-a]` removed before tokenization so the citation
metadata doesn't dilute the coverage score.

This is intentionally NOT a calibrated hallucination rate. It is a
*flag* — strong but imperfect, useful for triage, not for benchmarks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .wiki_corpus import extract_citation_refs, split_sentences, tokenize

# Strip `[ref-x]` markers from a sentence before tokenizing for the
# coverage calculation. Without this, citation metadata would inflate
# the sentence's token count and lower the score artificially.
_CITATION_STRIP_RE = re.compile(r"\[[A-Za-z0-9_.~-]+\]")


@dataclass(frozen=True)
class GroundednessScore:
    """Per-sentence attribution result."""

    sentence: str
    cited_refs: list[str]
    unresolved_refs: list[str] = field(default_factory=list)
    score: float = 0.0
    # Token-set diagnostics for the UI (matched tokens / sentence tokens).
    matched_tokens: int = 0
    sentence_tokens: int = 0
    evidence_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "sentence": self.sentence,
            "cited_refs": list(self.cited_refs),
            "unresolved_refs": list(self.unresolved_refs),
            "score": round(self.score, 4),
            "matched_tokens": self.matched_tokens,
            "sentence_tokens": self.sentence_tokens,
            "evidence_tokens": self.evidence_tokens,
        }


def jaccard(a: set[str], b: set[str]) -> float:
    """Token-set Jaccard similarity. Empty/empty is 0.0 by convention —
    it carries no information, so we don't claim a perfect match."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def sentence_coverage(sentence_tokens: set[str], evidence_tokens: set[str]) -> float:
    """Fraction of sentence tokens found in evidence.

    Empty sentence -> 0.0 (no claim made, nothing to support). Empty
    evidence with non-empty sentence -> 0.0 (no support available).
    """
    if not sentence_tokens:
        return 0.0
    matched = sentence_tokens & evidence_tokens
    return len(matched) / len(sentence_tokens)


def _strip_citations(text: str) -> str:
    """Remove `[ref-x]` markers so the sentence tokenization reflects
    only the claim, not the citation metadata."""
    return _CITATION_STRIP_RE.sub("", text)


def compute_sentence_groundedness(
    sentence: str,
    cited_refs: list[str],
    evidence_map: dict[str, str],
) -> GroundednessScore:
    """Compute sentence-token recall over the union of cited evidence.

    Unknown ref_ids (LLM hallucinated `[ref-doesnt-exist]`) are
    reported in `unresolved_refs` but excluded from the score
    computation. The UI surfaces these so the reviewer can spot
    fabricated citations separately from a real coverage gap.
    """
    claim = _strip_citations(sentence)
    sent_tokens = set(tokenize(claim))
    evidence_tokens: set[str] = set()
    resolved: list[str] = []
    unresolved: list[str] = []
    for rid in cited_refs:
        text = evidence_map.get(rid)
        if text is None:
            unresolved.append(rid)
            continue
        resolved.append(rid)
        evidence_tokens |= set(tokenize(text))
    matched = sent_tokens & evidence_tokens
    score = sentence_coverage(sent_tokens, evidence_tokens)
    return GroundednessScore(
        sentence=sentence,
        cited_refs=resolved,
        unresolved_refs=unresolved,
        score=score,
        matched_tokens=len(matched),
        sentence_tokens=len(sent_tokens),
        evidence_tokens=len(evidence_tokens),
    )


def groundedness_for_answer(
    answer: str,
    evidence_map: dict[str, str],
) -> list[GroundednessScore]:
    """Split `answer` into sentences and score each.

    Citations are extracted per-sentence so a multi-citation answer
    gets per-sentence attribution. The overall answer-level score is
    the mean of the per-sentence scores; the UI displays both.
    """
    sents = split_sentences(answer)
    scores: list[GroundednessScore] = []
    for sent in sents:
        cited = extract_citation_refs(sent)
        scores.append(compute_sentence_groundedness(sent, cited, evidence_map))
    return scores


def answer_overall_groundedness(scores: list[GroundednessScore]) -> float:
    """Mean of per-sentence scores; 0.0 for an empty list."""
    if not scores:
        return 0.0
    return sum(s.score for s in scores) / len(scores)
