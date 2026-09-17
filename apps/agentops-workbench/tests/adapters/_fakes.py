"""Deterministic embedding/rerank test doubles for WikiRagAdapter (ADR-0010).

Used only by tests -- never imported from `src/`. `FakeEmbeddingBackend`
models "semantic" matching by keyword -> vector direction, so a test can
assert a query with different words than the document still ranks it first
(the exact failure class dense retrieval exists to fix), without needing a
real model or any network access.
"""
from __future__ import annotations

from collections.abc import Callable


class FakeEmbeddingBackend:
    """`keyword_vectors` maps a lowercase substring to a fixed direction.

    `_vec(text)` sums the vectors of every keyword found as a substring of
    `text` (case-insensitive) and L2-normalizes the result. Text matching no
    keyword embeds to the zero vector, which has cosine similarity 0.0 with
    everything -- i.e. it behaves like true "no semantic relation" input.
    """

    def __init__(self, keyword_vectors: dict[str, list[float]]) -> None:
        if not keyword_vectors:
            raise ValueError("keyword_vectors must be non-empty")
        self._keywords = keyword_vectors
        self.dim = len(next(iter(keyword_vectors.values())))

    def _vec(self, text: str) -> list[float]:
        lowered = text.lower()
        vec = [0.0] * self.dim
        matched = False
        for kw, kv in self._keywords.items():
            if kw in lowered:
                matched = True
                for i, v in enumerate(kv):
                    vec[i] += v
        if not matched:
            return vec
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class FakeRerankBackend:
    """Deterministic reranker. Defaults to scoring by verbatim query overlap;
    pass `score_fn` to script an exact ordering for a test."""

    def __init__(self, score_fn: Callable[[str, str], float] | None = None) -> None:
        self._score_fn = score_fn
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        self.calls.append((query, list(documents)))
        if self._score_fn is not None:
            return [self._score_fn(query, d) for d in documents]
        q = query.lower()
        return [1.0 if q in d.lower() else 0.0 for d in documents]
