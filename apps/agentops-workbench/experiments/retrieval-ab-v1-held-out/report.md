# Retrieval A/B report (split=held_out, k=5)

n=2 queries. Metrics are file-level (chunk hits collapsed to their parent via `collapse_to_parents`) so whole-file and chunk-based modes are scored on the same unit.

| mode | Hit@k | R@k | P@k | MRR | nDCG@k | index_s | p50_ms |
|---|---|---|---|---|---|---|---|
| bm25 | 1.000 | 1.000 | 0.100 | 0.125 | 0.715 | 0.00 | 0.1 |
| dense | 1.000 | 1.000 | 0.100 | 0.500 | 1.000 | 0.40 | 4.0 |
| hybrid | 1.000 | 1.000 | 0.100 | 0.250 | 0.815 | 0.09 | 4.0 |
| hybrid_rerank | 1.000 | 1.000 | 0.100 | 0.500 | 1.000 | 0.12 | 105.0 |
| tfidf | 0.500 | 0.500 | 0.000 | 0.083 | 0.500 | 0.00 | 0.0 |

## Delta vs bm25 (baseline)

| mode | ΔHit@k | ΔR@k | ΔP@k | ΔMRR | ΔnDCG@k |
|---|---|---|---|---|---|
| dense | +0.000 | +0.000 | +0.000 | +0.375 | +0.285 |
| hybrid | +0.000 | +0.000 | +0.000 | +0.125 | +0.100 |
| hybrid_rerank | +0.000 | +0.000 | +0.000 | +0.375 | +0.285 |
| tfidf | -0.500 | -0.500 | -0.100 | -0.042 | -0.215 |

## Per-family nDCG@k

| mode | no_answer | paraphrase |
|---|---|---|
| bm25 | 1.000 | 0.431 |
| dense | 1.000 | 1.000 |
| hybrid | 1.000 | 0.631 |
| hybrid_rerank | 1.000 | 1.000 |
| tfidf | 1.000 | 0.000 |

_Caveat: this run's `n` is illustrative, not statistically settled. See docs/adr/0010-dense-retrieval-and-reranking.md for the metrics' documented limitations (Citation Precision/Recall track prompt compliance, not retrieval quality, at the answer-level layer)._
