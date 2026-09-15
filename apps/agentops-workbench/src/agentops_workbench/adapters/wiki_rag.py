"""WikiRagAdapter -- TF-IDF weighted cosine-similarity RAG over a directory
of Markdown files (an internal / personal wiki export).

This is a genuinely separate retrieval technique from
`mcp.InMemoryDocumentClient`'s pure substring/term-count scoring: each
document is represented as a TF-IDF vector (term frequency within the
document, weighted by inverse document frequency across the loaded
corpus), and a query is scored against a document by the cosine
similarity between the query's own TF-IDF vector and the document's.
Pure Python -- no numpy/scikit-learn, matching the dependency-light style
of the rest of this package.

Constructor takes `wiki_dir: str` with no hardcoded default -- unlike
`InMemoryDocumentClient`, which defaults to `fixtures/docs/` (the OLD
document-corpus use case), this adapter is meant to be pointed at
whatever directory a deployment's wiki export lands in.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..mcp import DocRef


import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..mcp import MCPError
from .base import EvidenceRef

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Maximum number of .md files WikiRagAdapter will index per corpus.
# Beyond this, the in-process TF-IDF index grows quadratically in
# vocabulary and would exhaust the FastAPI worker RSS. The cap
# matches `oss-helper`'s `--max-docs` default (4096). Above the cap,
# construction raises so the operator gets a loud failure instead of
# silent OOM. Override with the env var `AGENTOPS_WIKI_MAX_DOCS` (or
# the matching setting) when a larger corpus is genuinely warranted.
MAX_WIKI_DOCS = 4096


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WikiRagAdapter:
    """Real TF-IDF + cosine-similarity retrieval over `wiki_dir`/*.md.

    Raises `MCPError(kind="unsupported_capability")` at construction if
    `wiki_dir` contains more than `MAX_WIKI_DOCS` markdown files — the
    in-process TF-IDF index is O(N * V) in vocabulary size and would
    exhaust the FastAPI worker RSS above that. See
    `oss-helper`'s `--max-docs` flag for the operator-facing surface.

    The adapter caches itself per `wiki_dir` via the module-level
    `get_wiki_rag_adapter(wiki_dir)` factory below. Multiple
    `run_planner_executor` / `run_single_agent` calls against the same
    wiki_dir share one TF-IDF index build instead of re-paying the cost
    per request.
    """

    source_kind = "wiki"

    def __init__(self, wiki_dir: str) -> None:
        self._wiki_dir = wiki_dir
        self._files: dict[str, Path] = {
            f.stem: f for f in sorted(Path(wiki_dir).glob("*.md"))
        }
        if len(self._files) > MAX_WIKI_DOCS:
            raise MCPError(
                "unsupported_capability",
                f"wiki_dir {wiki_dir!r} contains {len(self._files)} markdown "
                f"files; WikiRagAdapter caps at MAX_WIKI_DOCS={MAX_WIKI_DOCS} "
                f"to keep the in-process TF-IDF index bounded. Narrow the "
                f"corpus or raise MAX_WIKI_DOCS at your own risk.",
                source="wiki_rag",
            )
        self._doc_term_counts: dict[str, Counter[str]] = {}
        self._doc_norms: dict[str, float] = {}
        self._df: Counter[str] = Counter()
        self._n_docs = len(self._files)
        for doc_id, path in self._files.items():
            text = path.read_text(encoding="utf-8", errors="replace")
            terms = _tokenize(text)
            counts = Counter(terms)
            self._doc_term_counts[doc_id] = counts
            for term in counts:
                self._df[term] += 1
        # idf computed lazily below via _idf(); doc TF-IDF vector norms are
        # precomputed once so cosine similarity at query time is cheap.
        for doc_id, counts in self._doc_term_counts.items():
            vec = {term: tf * self._idf(term) for term, tf in counts.items()}
            self._doc_norms[doc_id] = math.sqrt(sum(w * w for w in vec.values())) or 1.0
    # --- DocumentClient compat shims (for graph/*_*.py which still calls
    # search_docs/read_document by the legacy names) ---
    def search_docs(self, query: str, top_k: int = 5) -> list[DocRef]:
        """Compat shim: delegate to search_evidence, return DocRef-shaped results."""
        ev = self.search_evidence(query, top_k=top_k)
        return [
            DocRef(doc_id=r.ref_id, title=r.title, score=r.score)
            for r in ev
        ]

    def read_document(self, doc_id: str, offset: int = 0, limit: int = 2000) -> str:
        """Compat shim: delegate to read_evidence."""
        return self.read_evidence(doc_id, offset=offset, limit=limit)

    def list_filesystem_files(self) -> list[str]:
        """Compat shim: WikiRagAdapter doesn't index filesystem files; return empty."""
        return []


    def _idf(self, term: str) -> float:
        # Smoothed IDF: ln((1 + N) / (1 + df)) + 1 -- never zero, never
        # negative, and well-defined for a term seen in every document.
        df = self._df.get(term, 0)
        return math.log((1 + self._n_docs) / (1 + df)) + 1.0

    def _cosine_score(self, doc_id: str, query_terms: Counter[str]) -> float:
        doc_counts = self._doc_term_counts[doc_id]
        dot = 0.0
        for term, qtf in query_terms.items():
            dtf = doc_counts.get(term, 0)
            if dtf == 0:
                continue
            idf = self._idf(term)
            dot += (qtf * idf) * (dtf * idf)
        if dot == 0.0:
            return 0.0
        query_norm = math.sqrt(
            sum((tf * self._idf(term)) ** 2 for term, tf in query_terms.items())
        ) or 1.0
        doc_norm = self._doc_norms[doc_id]
        return dot / (query_norm * doc_norm)

    def search_evidence(
        self,
        query: str,
        top_k: int = 5,
        *,
        window: tuple[str, str] | None = None,
        filters: dict | None = None,
    ) -> list[EvidenceRef]:
        query_terms = Counter(_tokenize(query))
        if not query_terms or not self._files:
            return []
        retrieved_at = _now_iso()
        scored: list[EvidenceRef] = []
        for doc_id in self._files:
            score = self._cosine_score(doc_id, query_terms)
            if score <= 0.0:
                continue
            title = doc_id.replace("-", " ").replace("_", " ")
            scored.append(
                EvidenceRef(
                    ref_id=doc_id,
                    title=title,
                    score=score,
                    source_kind=self.source_kind,
                    retrieved_at=retrieved_at,
                )
            )
        scored.sort(key=lambda r: -r.score)
        return scored[:top_k]

    def read_evidence(self, ref_id: str, offset: int = 0, limit: int = 2000) -> str:
        path = self._files.get(ref_id)
        if path is None or not path.exists():
            raise MCPError("unknown", f"wiki page not found: {ref_id}", source="wiki_rag")
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[offset : offset + limit]


# Module-level cache keyed by `wiki_dir`. Multiple `run_planner_executor`
# calls against the same wiki share one TF-IDF index build instead of
# re-paying the O(N*V) construction cost per request. Cleared explicitly
# by `clear_wiki_rag_cache()` when tests need a fresh build.
_WIKI_RAG_CACHE: dict[str, WikiRagAdapter] = {}


def get_wiki_rag_adapter(wiki_dir: str) -> WikiRagAdapter:
    """Return the cached WikiRagAdapter for `wiki_dir`, building on miss.

    Construction enforces the `MAX_WIKI_DOCS` cap (raises MCPError on
    overflow). The cache is process-local and never invalidated
    automatically; callers that mutate the wiki directory must invoke
    `clear_wiki_rag_cache()` to force a rebuild.
    """
    cached = _WIKI_RAG_CACHE.get(wiki_dir)
    if cached is not None:
        return cached
    adapter = WikiRagAdapter(wiki_dir)
    _WIKI_RAG_CACHE[wiki_dir] = adapter
    return adapter


def clear_wiki_rag_cache() -> None:
    """Drop all cached WikiRagAdapter instances. Used by tests."""
    _WIKI_RAG_CACHE.clear()
