"""WikiRagAdapter -- lexical + dense/hybrid RAG over a directory of Markdown
files (an internal / personal wiki export).

Five selectable retrieval modes (ADR-0010: docs/adr/0010-dense-retrieval-and-reranking.md):

- `retrieval="tfidf"` (default): each document is a TF-IDF vector (term
  frequency within the document, weighted by inverse document frequency
  across the loaded corpus); a query is scored by cosine similarity
  between the query's own TF-IDF vector and the document's.
- `retrieval="bm25"`: Okapi BM25 (Robertson & Sparck Jones), k1=1.5,
  b=0.75, +1-smoothed IDF. Saturates term-frequency (repeating a matched
  term yields diminishing score gains, unlike TF-IDF's near-linear
  term-frequency contribution) and normalizes by document length
  relative to the corpus average -- generally a better lexical ranker
  for wikis with mixed short/long notes.
- `retrieval="dense"`: chunk-level cosine similarity over a small
  int8-quantized ONNX embedding model (`fastembed`, CPU-only, no torch).
  Finds a chunk that shares no vocabulary with the query at all (a
  synonym or paraphrase) -- the one failure class no lexical mode above
  can ever recover from.
- `retrieval="hybrid"`: chunk-level BM25 fused with `dense` via
  Reciprocal Rank Fusion.
- `retrieval="hybrid_rerank"`: `hybrid`'s top candidates re-scored by a
  CPU cross-encoder.

`tfidf`/`bm25` above are `_LEXICAL_MODES` -- pure Python, no numpy/
scikit-learn, matching the dependency-light style of the rest of this
package, and PROVABLY untouched by the three modes below them (see
tests/adapters/test_wiki_rag_lexical_frozen.py). The three non-lexical
modes are gated behind the optional `[dense]` install extra and never
import `fastembed`/`onnxruntime` unless one of them is actually selected
-- ADR-0010 has the full cost/RAM-budget accounting for a GPU-less
8GB deployment.

This is a genuinely separate family of retrieval techniques from
`mcp.InMemoryDocumentClient`'s pure substring/term-count scoring.

Constructor takes `wiki_dir: str` with no hardcoded default -- unlike
`InMemoryDocumentClient`, which defaults to `fixtures/docs/` (the OLD
document-corpus use case), this adapter is meant to be pointed at
whatever directory a deployment's wiki export lands in.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..mcp import DocRef


import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
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

# Directory names skipped when walking wiki_dir recursively. The walk is
# generic across Obsidian vaults and arbitrary ~/dev/mywiki-style exports,
# so we exclude the metadata / VCS / cache dirs that routinely appear in
# such trees and would either bloat the index or pull in non-content
# (e.g. `.obsidian/workspace.json`, `.git/HEAD`, `node_modules/README.md`).
# `_flat` is oss-helper's flattened-docs staging dir — content there is
# already merged by the upstream acquisition step, so re-indexing it
# would double-count.
#
# Any directory whose name starts with `.` is also skipped — Obsidian
# plugin metadata (`.obsidian/`, `.metagraph/`, `.trash/`) and copies of
# other projects' `.worktrees/` clones live there, not wiki content.
# Users who actually want a `.archive/` directory indexed can rename it.
SKIP_DIR_NAMES: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".obsidian",
    ".dev-kit",
    ".claude",
    ".codex",
    ".serena",
    ".gemini",
    ".metagraph",
    ".trash",
    ".worktrees",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "_flat",
})


def _is_skipped_dir(part: str) -> bool:
    """True if a directory component should be skipped during the walk.

    Explicit list (SKIP_DIR_NAMES) is checked first; then the blanket
    rule — any name starting with `.` is skipped. This catches plugin
    metadata dirs (`.metagraph/`, `.trash/`, ...) that aren't enumerated
    explicitly above and protects against future unknown dot-directories
    leaking into the index.
    """
    if part in SKIP_DIR_NAMES:
        return True
    if part.startswith("."):
        return True
    return False


def collect_wiki_files(wiki_dir: Path) -> dict[str, Path]:
    """Walk `wiki_dir` recursively for `.md` files and return {ref_id: path}.

    Generic across layouts: a flat `~/dev/mywiki/*.md` tree and an Obsidian
    vault with nested category subdirs (e.g. `wiki/<domain>/<slug>.md`)
    both work. Junk directories — anything in `SKIP_DIR_NAMES` or starting
    with `.` — are skipped along with hidden files.

    ref_id contract:
      - Files directly at `wiki_dir` root  ->  `f.stem`  (back-compat:
        existing tests + oss-helper's `_flat` layout rely on this).
      - Files nested in subdirs            ->  `__`-joined path with the
        suffix stripped, e.g. `langgraph/checkpointing.md` becomes
        `langgraph__checkpointing`.

    On ref_id collision (two files with the same stem inside the same dir
    is impossible on POSIX, but cross-dir collisions are real), the second
    occurrence gets a `__N` suffix so every file stays reachable.
    """
    if not wiki_dir.exists() or not wiki_dir.is_dir():
        return {}
    out: dict[str, Path] = {}
    for path in sorted(wiki_dir.rglob("*.md")):
        try:
            rel = path.relative_to(wiki_dir)
        except ValueError:
            continue
        # Skip when any directory component of the relative path is junk.
        # The trailing component is the filename itself, not a dir.
        if any(_is_skipped_dir(part) for part in rel.parts[:-1]):
            continue
        # Skip hidden files at the root (`.foo.md`).
        if path.name.startswith("."):
            continue
        # Compute a stable ref_id.
        if len(rel.parts) == 1:
            ref_id = path.stem
        else:
            ref_id = "__".join(rel.with_suffix("").parts)
        # Resolve collisions deterministically.
        if ref_id in out:
            n = 2
            while f"{ref_id}__{n}" in out:
                n += 1
            ref_id = f"{ref_id}__{n}"
        out[ref_id] = path
    return out


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_LEXICAL_MODES = frozenset({"tfidf", "bm25"})

# ADR-0010: dense (chunk-level cosine), hybrid (BM25+dense via RRF), and
# hybrid_rerank (hybrid's top candidates re-scored by a cross-encoder).
# Strictly additive -- _LEXICAL_MODES' code paths are untouched by their
# presence; see tests/adapters/test_wiki_rag_lexical_frozen.py.
_VALID_RETRIEVAL_MODES = _LEXICAL_MODES | frozenset({"dense", "hybrid", "hybrid_rerank"})

# Standard Okapi BM25 free parameters (Robertson & Sparck Jones defaults
# used by most implementations, e.g. rank_bm25, Lucene's pre-6.0 default).
_BM25_K1 = 1.5
_BM25_B = 0.75

# ADR-0010 non-lexical retrieval parameters.
# A vault capped at MAX_WIKI_DOCS=4096 files yields at most ~20k chunks at
# _CHUNK_MAX_CHARS-sized pieces; 20k * 384 dims * 4 bytes (float32) = 30MB,
# an exact brute-force matvec over which is ~10ms -- see ADR-0010 Decision
# §4 for why this stays a plain matrix rather than pulling in pgvector.
MAX_WIKI_CHUNKS = 20_000
_RRF_K = 60                 # Cormack, Clarke & Buttcher (2009) RRF constant
_RRF_LEG_DEPTH = 50         # candidates pulled from each leg before fusion
_RERANK_CANDIDATES = 20     # hybrid_rerank: how many fused candidates get scored
_DENSE_MIN_COSINE = 0.30    # floor below which a dense hit is treated as noise
_DENSE_MODEL = "BAAI/bge-small-en-v1.5"
_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


@dataclass(frozen=True)
class _Chunk:
    """One chunk of a wiki file, used only by non-lexical retrieval modes."""

    ref_id: str              # f"{parent_ref_id}#c{n}"
    parent_ref_id: str
    heading_path: tuple[str, ...]
    text: str                # heading-prefixed text actually embedded
    raw_start: int            # offsets into the parent file's raw text
    raw_end: int


class EmbeddingBackend(Protocol):
    """Seam for the dense encoder (ADR-0010 §3). `fastembed`-backed by
    default; tests inject a deterministic fake (tests/adapters/_fakes.py)."""

    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class RerankBackend(Protocol):
    """Seam for the cross-encoder reranker (ADR-0010 §3)."""

    def rerank(self, query: str, documents: list[str]) -> list[float]: ...


# Process-global singleton cache for real embedding/rerank backends, keyed
# by model name. Deliberately NOT per-adapter: wiki_corpus.DEFAULT_CAP keeps
# up to 16 corpora alive at once, and a per-adapter model would multiply the
# ~100-150MB model footprint by that many -- see ADR-0010 §3.
_BACKEND_CACHE: dict[str, object] = {}
_BACKEND_LOCK = threading.Lock()


class _FastEmbedBackend:
    """`fastembed`-backed EmbeddingBackend. Imported lazily -- constructing
    this is the only thing that pulls `fastembed`/`onnxruntime` into the
    process, and only non-lexical modes ever reach this constructor."""

    dim = 384

    def __init__(self, model_name: str = _DENSE_MODEL) -> None:
        from fastembed import TextEmbedding  # noqa: PLC0415 - intentionally lazy

        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.embed([text]))).tolist()


class _FastEmbedRerankBackend:
    """`fastembed`-backed RerankBackend, same lazy-import discipline.

    `TextCrossEncoder.rerank()` returns raw (unbounded, can be negative)
    logits -- confirmed empirically, not just from docs. Sigmoid-transform
    them so callers (and the UI's "0-1, higher = more relevant" copy) get an
    actual probability-like score; sigmoid is monotonic, so ranking order is
    unaffected.
    """

    def __init__(self, model_name: str = _RERANK_MODEL) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: PLC0415

        self._model = TextCrossEncoder(model_name=model_name)

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [1.0 / (1.0 + math.exp(-logit)) for logit in self._model.rerank(query, documents)]


def _default_embedding_backend() -> EmbeddingBackend:
    with _BACKEND_LOCK:
        key = f"embed:{_DENSE_MODEL}"
        cached = _BACKEND_CACHE.get(key)
        if cached is None:
            cached = _FastEmbedBackend(_DENSE_MODEL)
            _BACKEND_CACHE[key] = cached
        return cached  # type: ignore[return-value]


def _default_rerank_backend() -> RerankBackend:
    with _BACKEND_LOCK:
        key = f"rerank:{_RERANK_MODEL}"
        cached = _BACKEND_CACHE.get(key)
        if cached is None:
            cached = _FastEmbedRerankBackend(_RERANK_MODEL)
            _BACKEND_CACHE[key] = cached
        return cached  # type: ignore[return-value]


def clear_backend_cache() -> None:
    """Drop cached embedding/rerank backends. Used by tests."""
    with _BACKEND_LOCK:
        _BACKEND_CACHE.clear()


class WikiRagAdapter:
    """Real TF-IDF or BM25 lexical retrieval over `wiki_dir`/*.md.

    Raises `MCPError(kind="unsupported_capability")` at construction if
    `wiki_dir` contains more than `MAX_WIKI_DOCS` markdown files — the
    in-process index is O(N * V) in vocabulary size and would exhaust
    the FastAPI worker RSS above that. See `oss-helper`'s `--max-docs`
    flag for the operator-facing surface.

    The adapter caches itself per `wiki_dir` via the module-level
    `get_wiki_rag_adapter(wiki_dir)` factory below. Multiple
    `run_planner_executor` / `run_single_agent` calls against the same
    wiki_dir share one index build instead of re-paying the cost per
    request.
    """

    source_kind = "wiki"

    def __init__(
        self,
        wiki_dir: str,
        *,
        retrieval: str = "tfidf",
        embedder: EmbeddingBackend | None = None,
        reranker: RerankBackend | None = None,
    ) -> None:
        if retrieval not in _VALID_RETRIEVAL_MODES:
            raise ValueError(
                f"retrieval={retrieval!r} is not supported; "
                f"choose one of {sorted(_VALID_RETRIEVAL_MODES)}"
            )
        self._wiki_dir = wiki_dir
        self._retrieval = retrieval
        # Generic across Obsidian vaults and arbitrary ~/dev/mywiki-style
        # exports: walk recursively, skip junk dirs (see SKIP_DIR_NAMES).
        self._files: dict[str, Path] = collect_wiki_files(Path(wiki_dir))
        if len(self._files) > MAX_WIKI_DOCS:
            raise MCPError(
                "unsupported_capability",
                f"wiki_dir {wiki_dir!r} contains {len(self._files)} markdown "
                f"files; WikiRagAdapter caps at MAX_WIKI_DOCS={MAX_WIKI_DOCS} "
                f"to keep the in-process index bounded. Narrow the "
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
        # BM25 needs per-doc length + the corpus average (its length-
        # normalization term). Cheap, so compute unconditionally.
        self._doc_lengths: dict[str, int] = {
            doc_id: sum(counts.values()) for doc_id, counts in self._doc_term_counts.items()
        }
        self._avgdl = (
            sum(self._doc_lengths.values()) / self._n_docs if self._n_docs else 0.0
        )

        # ADR-0010: chunk/dense/rerank state. Built ONLY for non-lexical
        # modes -- a tfidf/bm25 adapter never touches any of this, which is
        # what tests/adapters/test_wiki_rag_lexical_frozen.py enforces.
        self._chunks: dict[str, _Chunk] = {}
        self._chunk_term_counts: dict[str, Counter[str]] = {}
        self._chunk_df: Counter[str] = Counter()
        self._chunk_lengths: dict[str, int] = {}
        self._chunk_avgdl: float = 0.0
        self._embedder: EmbeddingBackend | None = None
        self._reranker: RerankBackend | None = reranker
        self._dense_matrix = None  # numpy float32 (N, dim), L2-normalized rows
        self._dense_ref_ids: list[str] = []
        if retrieval not in _LEXICAL_MODES:
            self._build_chunk_index()
            self._build_chunk_lexical_index()
            self._embedder = embedder or _default_embedding_backend()
            self._build_dense_index()

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


    def term_counts(self, ref_id: str) -> Counter[str] | None:
        """Term-count accessor spanning both whole-file and chunk indices.

        `wiki_corpus.search_with_timing` uses this instead of reaching into
        `_doc_term_counts` directly, so it works for chunk ref_ids too. For
        a file ref_id under a lexical mode this returns the identical
        `Counter` object `_doc_term_counts` already held -- no behaviour
        change for the lexical path.
        """
        if ref_id in self._doc_term_counts:
            return self._doc_term_counts[ref_id]
        return self._chunk_term_counts.get(ref_id)

    def _build_chunk_index(self) -> None:
        from ..chunking import chunk_markdown  # noqa: PLC0415 - avoid a module cycle

        for parent_id, path in self._files.items():
            text = path.read_text(encoding="utf-8", errors="replace")
            for n, spec in enumerate(chunk_markdown(text)):
                chunk_id = f"{parent_id}#c{n}"
                self._chunks[chunk_id] = _Chunk(
                    ref_id=chunk_id,
                    parent_ref_id=parent_id,
                    heading_path=spec.heading_path,
                    text=spec.text,
                    raw_start=spec.raw_start,
                    raw_end=spec.raw_end,
                )
        if len(self._chunks) > MAX_WIKI_CHUNKS:
            raise MCPError(
                "unsupported_capability",
                f"wiki_dir {self._wiki_dir!r} produced {len(self._chunks)} chunks "
                f"under retrieval={self._retrieval!r}; WikiRagAdapter caps "
                f"non-lexical modes at MAX_WIKI_CHUNKS={MAX_WIKI_CHUNKS}. Narrow "
                f"the corpus or raise MAX_WIKI_CHUNKS at your own risk.",
                source="wiki_rag",
            )

    def _build_chunk_lexical_index(self) -> None:
        """Chunk-level BM25 term stats, mirroring the file-level index above
        (independent counters -- the file-level ones stay untouched)."""
        for chunk_id, chunk in self._chunks.items():
            counts = Counter(_tokenize(chunk.text))
            self._chunk_term_counts[chunk_id] = counts
            for term in counts:
                self._chunk_df[term] += 1
            self._chunk_lengths[chunk_id] = sum(counts.values())
        n_chunks = len(self._chunks)
        self._chunk_avgdl = (
            sum(self._chunk_lengths.values()) / n_chunks if n_chunks else 0.0
        )

    def _build_dense_index(self) -> None:
        import numpy as np  # noqa: PLC0415 - lazy: only non-lexical modes need it

        chunk_ids = list(self._chunks)
        if not chunk_ids:
            return
        assert self._embedder is not None
        vectors = self._embedder.embed_documents([self._chunks[c].text for c in chunk_ids])
        matrix = np.asarray(vectors, dtype="float32")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._dense_matrix = matrix / norms
        self._dense_ref_ids = chunk_ids

    def _dense_candidates(self, query: str, depth: int) -> list[tuple[str, float]]:
        if self._dense_matrix is None or not self._dense_ref_ids:
            return []
        import numpy as np  # noqa: PLC0415

        assert self._embedder is not None
        qvec = np.asarray(self._embedder.embed_query(query), dtype="float32")
        qnorm = float(np.linalg.norm(qvec))
        if qnorm == 0.0:
            return []
        qvec = qvec / qnorm
        sims = self._dense_matrix @ qvec
        order = np.argsort(-sims)[:depth]
        out: list[tuple[str, float]] = []
        for idx in order:
            score = float(sims[idx])
            if score < _DENSE_MIN_COSINE:
                continue
            out.append((self._dense_ref_ids[int(idx)], score))
        return out

    def _chunk_bm25_idf(self, term: str) -> float:
        df = self._chunk_df.get(term, 0)
        n = len(self._chunks)
        return math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    def _chunk_bm25_candidates(
        self, query_terms: Counter[str], depth: int
    ) -> list[tuple[str, float]]:
        scored: list[tuple[str, float]] = []
        for chunk_id, counts in self._chunk_term_counts.items():
            doc_len = self._chunk_lengths[chunk_id]
            score = 0.0
            for term in query_terms:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                idf = self._chunk_bm25_idf(term)
                denom = tf + _BM25_K1 * (
                    1 - _BM25_B + _BM25_B * (doc_len / self._chunk_avgdl)
                )
                score += idf * (tf * (_BM25_K1 + 1)) / denom
            if score > 0.0:
                scored.append((chunk_id, score))
        scored.sort(key=lambda kv: -kv[1])
        return scored[:depth]

    def _rrf_fuse(self, *rank_lists: list[tuple[str, float]]) -> list[tuple[str, float]]:
        """Reciprocal Rank Fusion (Cormack, Clarke & Buttcher 2009)."""
        scores: dict[str, float] = {}
        for ranked in rank_lists:
            for rank, (chunk_id, _score) in enumerate(ranked):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
        return sorted(scores.items(), key=lambda kv: -kv[1])

    def _rerank(
        self, query: str, candidates: list[tuple[str, float]]
    ) -> list[tuple[str, float]]:
        if not candidates:
            return []
        top = candidates[:_RERANK_CANDIDATES]
        if self._reranker is None:
            self._reranker = _default_rerank_backend()
        docs = [self._chunks[chunk_id].text for chunk_id, _ in top]
        scores = self._reranker.rerank(query, docs)
        reranked = list(zip((chunk_id for chunk_id, _ in top), scores, strict=True))
        reranked.sort(key=lambda kv: -kv[1])
        return reranked

    def _search_chunked(self, query: str, top_k: int) -> list[EvidenceRef]:
        query_terms = Counter(_tokenize(query))
        if not query_terms or not self._chunks:
            return []
        retrieved_at = _now_iso()

        if self._retrieval == "dense":
            ranked = self._dense_candidates(query, depth=max(top_k, _RRF_LEG_DEPTH))
        else:
            dense_ranked = self._dense_candidates(query, depth=_RRF_LEG_DEPTH)
            bm25_ranked = self._chunk_bm25_candidates(query_terms, depth=_RRF_LEG_DEPTH)
            fused = self._rrf_fuse(dense_ranked, bm25_ranked)
            ranked = self._rerank(query, fused) if self._retrieval == "hybrid_rerank" else fused

        out: list[EvidenceRef] = []
        for chunk_id, score in ranked[:top_k]:
            chunk = self._chunks[chunk_id]
            parent_title = chunk.parent_ref_id.replace("-", " ").replace("_", " ")
            heading = " > ".join(chunk.heading_path)
            title = f"{parent_title} :: {heading}" if heading else parent_title
            out.append(
                EvidenceRef(
                    ref_id=chunk_id,
                    title=title,
                    score=score,
                    source_kind=self.source_kind,
                    retrieved_at=retrieved_at,
                )
            )
        return out

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

    def _bm25_idf(self, term: str) -> float:
        # Robertson-Sparck Jones IDF, +1-smoothed so it's never negative
        # for a term that appears in more than half the corpus.
        df = self._df.get(term, 0)
        return math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0)

    def _bm25_score(self, doc_id: str, query_terms: Counter[str]) -> float:
        doc_counts = self._doc_term_counts[doc_id]
        doc_len = self._doc_lengths[doc_id]
        score = 0.0
        for term in query_terms:
            tf = doc_counts.get(term, 0)
            if tf == 0:
                continue
            idf = self._bm25_idf(term)
            denom = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * (doc_len / self._avgdl))
            score += idf * (tf * (_BM25_K1 + 1)) / denom
        return score

    def _score(self, doc_id: str, query_terms: Counter[str]) -> float:
        if self._retrieval == "bm25":
            return self._bm25_score(doc_id, query_terms)
        return self._cosine_score(doc_id, query_terms)

    def _contributing_term_weight(self, term: str) -> float:
        """Term weight used only to rank "why this doc" contributing terms
        for the UI -- matches whichever IDF variant the active retrieval
        mode actually scores with."""
        if self._retrieval == "bm25":
            return self._bm25_idf(term)
        return self._idf(term)

    def search_evidence(
        self,
        query: str,
        top_k: int = 5,
        *,
        window: tuple[str, str] | None = None,
        filters: dict | None = None,
    ) -> list[EvidenceRef]:
        if self._retrieval not in _LEXICAL_MODES:
            return self._search_chunked(query, top_k)
        query_terms = Counter(_tokenize(query))
        if not query_terms or not self._files:
            return []
        retrieved_at = _now_iso()
        scored: list[EvidenceRef] = []
        for doc_id in self._files:
            score = self._score(doc_id, query_terms)
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
        if path is not None:
            if not path.exists():
                raise MCPError("unknown", f"wiki page not found: {ref_id}", source="wiki_rag")
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[offset : offset + limit]
        chunk = self._chunks.get(ref_id)
        if chunk is not None:
            parent_path = self._files[chunk.parent_ref_id]
            full_text = parent_path.read_text(encoding="utf-8", errors="replace")
            raw = full_text[chunk.raw_start : chunk.raw_end]
            return raw[offset : offset + limit]
        raise MCPError("unknown", f"wiki page not found: {ref_id}", source="wiki_rag")


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
