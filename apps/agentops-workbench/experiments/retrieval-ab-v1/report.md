# Retrieval A/B report (split=dev, k=5)

n=8 queries. Metrics are file-level (chunk hits collapsed to their parent via `collapse_to_parents`) so whole-file and chunk-based modes are scored on the same unit.

| mode | Hit@k | R@k | P@k | MRR | nDCG@k | index_s | p50_ms |
|---|---|---|---|---|---|---|---|
| bm25 | 1.000 | 1.000 | 0.463 | 0.875 | 1.000 | 0.00 | 0.0 |
| dense | 1.000 | 1.000 | 0.225 | 0.875 | 1.000 | 0.83 | 3.6 |
| hybrid | 1.000 | 1.000 | 0.225 | 0.875 | 1.000 | 0.10 | 3.4 |
| hybrid_rerank | 1.000 | 1.000 | 0.225 | 0.875 | 1.000 | 0.09 | 64.2 |
| tfidf | 1.000 | 1.000 | 0.463 | 0.812 | 0.954 | 0.00 | 0.0 |

## Delta vs bm25 (baseline)

| mode | ΔHit@k | ΔR@k | ΔP@k | ΔMRR | ΔnDCG@k |
|---|---|---|---|---|---|
| dense | +0.000 | +0.000 | -0.238 | +0.000 | +0.000 |
| hybrid | +0.000 | +0.000 | -0.238 | +0.000 | +0.000 |
| hybrid_rerank | +0.000 | +0.000 | -0.238 | +0.000 | +0.000 |
| tfidf | +0.000 | +0.000 | +0.000 | -0.062 | -0.046 |

## Per-family nDCG@k

| mode | acronym | multi_hop | no_answer | paraphrase | single_hop | synonym |
|---|---|---|---|---|---|---|
| bm25 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| dense | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hybrid_rerank | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| tfidf | 1.000 | 1.000 | 1.000 | 1.000 | 0.815 | 1.000 |

_Caveat: this run's `n` is illustrative, not statistically settled. See docs/adr/0010-dense-retrieval-and-reranking.md for the metrics' documented limitations (Citation Precision/Recall track prompt compliance, not retrieval quality, at the answer-level layer)._
