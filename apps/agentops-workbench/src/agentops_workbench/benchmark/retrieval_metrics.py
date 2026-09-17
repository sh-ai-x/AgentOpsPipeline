"""Retrieval-quality metrics for comparing WikiRagAdapter retrieval modes
(ADR-0010). Pure Python, stdlib only -- no numpy, so a comparison run has
no dependency beyond the retrieval modes it is measuring.

Deliberately separate from `benchmark/scorers.py::retrieval_recall_at_k`:
that function is typed to `BenchmarkCase` / `doc://`-style source refs for
the answer-level 30-case benchmark over `fixtures/docs/`. This module scores
a raw ranked ref_id list against a wiki gold set (`fixtures/wiki_eval/`)
instead. Only the empty-gold -> 1.0 convention is shared between the two.

Chunk-mode rankings (`"doc#c3"`) and whole-file rankings (`"doc"`) are made
comparable via `collapse_to_parents` -- callers should collapse before
computing file-level metrics; a separate `chunk`-scoped metric can be
computed on the un-collapsed ranking when the question is specifically
"did chunking help".
"""
from __future__ import annotations

import math


def collapse_to_parents(ranked_ref_ids: list[str]) -> list[str]:
    """Collapse chunk ref_ids (`"parent#cN"`) to their parent ref_id,
    keeping first occurrence order and dropping later duplicates. A
    no-op for whole-file ref_ids (which never contain `"#c"`)."""
    out: list[str] = []
    seen: set[str] = set()
    for ref_id in ranked_ref_ids:
        parent = ref_id.split("#c", 1)[0] if "#c" in ref_id else ref_id
        if parent not in seen:
            seen.add(parent)
            out.append(parent)
    return out


def hit_rate_at_k(gold: set[str], ranked: list[str], k: int) -> float:
    """1.0 if any gold ref_id appears in the top-k, else 0.0.

    Empty gold (a `no_answer` query) is trivially "hit" -- there is
    nothing to have missed.
    """
    if not gold:
        return 1.0
    return 1.0 if any(ref_id in gold for ref_id in ranked[:k]) else 0.0


def recall_at_k(gold: set[str], ranked: list[str], k: int) -> float:
    """|gold found in top-k| / |gold|. Empty gold -> 1.0 (scorers.py convention)."""
    if not gold:
        return 1.0
    found = sum(1 for ref_id in ranked[:k] if ref_id in gold)
    return found / len(gold)


def precision_at_k(gold: set[str], ranked: list[str], k: int) -> float:
    """|gold found in top-k| / |top-k returned|.

    Empty gold: 1.0 iff nothing was returned (there was nothing to
    wrongly return), 0.0 if anything was -- every one of it is a
    false positive by definition of an empty gold set.
    """
    top = ranked[:k]
    if not gold:
        return 1.0 if not top else 0.0
    if not top:
        return 0.0
    found = sum(1 for ref_id in top if ref_id in gold)
    return found / len(top)


def mrr(gold: set[str], ranked: list[str]) -> float:
    """1 / (rank of the first gold hit), 1-indexed. 0.0 if none found."""
    for i, ref_id in enumerate(ranked):
        if ref_id in gold:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(grades: dict[str, int], ranked: list[str], k: int) -> float:
    """Normalized DCG@k with graded relevance (Jarvelin & Kekalainen, 2002).

    `grades` maps ref_id -> a non-negative relevance grade (0 = irrelevant).
    A ref_id absent from `grades` is treated as grade 0. When every graded
    ref_id has grade 0 (the `no_answer` family: nothing in the corpus
    answers this query), IDCG is 0 and the score is trivially 1.0 -- there
    is no way to rank a nonexistent relevant set "wrong".
    """
    def _dcg(seq: list[str]) -> float:
        return sum(
            (2 ** grades.get(ref_id, 0) - 1) / math.log2(i + 2)
            for i, ref_id in enumerate(seq)
        )

    actual = _dcg(ranked[:k])
    ideal_order = sorted(grades, key=lambda r: -grades[r])[:k]
    ideal = _dcg(ideal_order)
    if ideal == 0.0:
        return 1.0
    return actual / ideal
