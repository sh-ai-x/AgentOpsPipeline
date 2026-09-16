"""WikiRagAdapter -- TF-IDF/BM25 lexical RAG over a directory of Markdown
files (an internal / personal wiki export).

Two selectable retrieval modes, both pure Python (no numpy/scikit-learn,
matching the dependency-light style of the rest of this package):

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

Real vector-embedding search (dense retrieval) is a deliberate
non-goal here: it needs either a heavy local embedding model (breaks
the dependency-light design) or a per-query call to a provider's
embeddings endpoint (network + cost per search). Left as a follow-up
once that tradeoff is settled.

This is a genuinely separate family of retrieval techniques from
`mcp.InMemoryDocumentClient`'s pure substring/term-count scoring.

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


_VALID_RETRIEVAL_MODES = frozenset({"tfidf", "bm25"})

# Standard Okapi BM25 free parameters (Robertson & Sparck Jones defaults
# used by most implementations, e.g. rank_bm25, Lucene's pre-6.0 default).
_BM25_K1 = 1.5
_BM25_B = 0.75


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

    def __init__(self, wiki_dir: str, *, retrieval: str = "tfidf") -> None:
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
