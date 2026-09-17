"""Per-`corpus_id` WikiRagAdapter registry + provenance-aware search.

Phase 9 design:
  - The browser File System Access API lets a reviewer pick a directory
    and read its .md files client-side. It then POSTs each file as
    {path, content, mtime} to /v1/wiki/index-files. The server writes
    them to a temp dir, builds a WikiRagAdapter on top, returns a
    corpus_id.
  - Subsequent /v1/wiki/search?corpus_id=... calls hit the registry,
    not the filesystem. The same WikiRagAdapter used by the
    planner_executor and single_agent topologies backs this too, now
    with a selectable retrieval mode ("tfidf" default, "bm25", or --
    ADR-0010 -- "dense" / "hybrid" / "hybrid_rerank") -- see
    WikiRagAdapter's module docstring for the tradeoffs.
  - Search results gain five trust fields (AC3): source_path,
    evidence_span (with character offsets), coverage, contributing_terms,
    mtime. For a chunk ref_id (ADR-0010's non-lexical modes), source_path
    and mtime are the PARENT file's -- a chunk isn't its own upload entry.
  - registry is process-local + LRU-capped. Persistent storage would
    mean keeping user files on server disk — a privacy regression.

The tokenization helpers (`tokenize`, `split_sentences`,
`extract_citation_refs`) are re-exported here from `text_utils.py` (moved
there in ADR-0010 to break an import cycle with `chunking.py`) so the
test suite can keep pinning them via `wiki_corpus.*` without depending on
the adapter's internal regex.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .adapters.wiki_rag import WikiRagAdapter
from .text_utils import extract_citation_refs, split_sentences, tokenize

__all__ = [
    "DEFAULT_CAP",
    "UnknownCorpusError",
    "WikiCorpusRegistry",
    "WikiSearchHit",
    "cleanup_corpus",
    "extract_citation_refs",
    "get_registry",
    "index_uploaded_files",
    "reset_registry_for_tests",
    "search",
    "search_with_timing",
    "split_sentences",
    "tokenize",
]

log = logging.getLogger(__name__)


# Default LRU cap. Each WikiRagAdapter holds ~ corpus_size * avg_terms
# counters in memory; 16 corpora × 4096 docs × ~50 unique terms is
# ~3M ints, well under the FastAPI worker RSS budget.
DEFAULT_CAP = 16


# ---- Errors ----


class UnknownCorpusError(KeyError):
    """Raised when a corpus_id is not in the registry."""

    def __init__(self, corpus_id: str) -> None:
        super().__init__(corpus_id)
        self.corpus_id = corpus_id


# ---- Result types ----


@dataclass(frozen=True)
class WikiSearchHit:
    """Single search result with the five trust fields mandated by AC3."""

    ref_id: str
    title: str
    score: float
    # Provenance (AC3).
    source_path: str
    evidence_span: str
    match_offsets: list[tuple[int, int]]   # char (start, end) into full doc
    coverage: float                       # matched query terms / total
    contributing_terms: list[str]         # top terms that pushed the score
    mtime: int                            # file mtime (epoch ms)
    # Optional Obsidian deep link: set when the indexed directory's
    # root contained `.obsidian/` AND the upload supplied `vault_name`.
    # Frontend uses this for one-click "open in vault" on every hit.
    obsidian_uri: str | None = None

    def to_dict(self) -> dict:
        return {
            "ref_id": self.ref_id,
            "title": self.title,
            "score": round(self.score, 4),
            "source_path": self.source_path,
            "evidence_span": self.evidence_span,
            "match_offsets": [list(o) for o in self.match_offsets],
            "coverage": round(self.coverage, 4),
            "contributing_terms": self.contributing_terms,
            "mtime": self.mtime,
            "obsidian_uri": self.obsidian_uri,
        }


# ---- Registry ----


def time_monotonic() -> float:
    """Thin wrapper so the dataclass default_factory can name a callable
    defined at module scope (no closure scope surprises across reimports)."""
    import time as _time
    return _time.monotonic()


@dataclass
class _CorpusEntry:
    corpus_id: str
    adapter: WikiRagAdapter
    work_dir: Path
    # Source path of each ref_id, captured at index time. We need this
    # because WikiRagAdapter._files stores only the absolute Path —
    # the user's "directory" can be anywhere; we remember the path
    # *inside* the user's pick so the UI shows a human-readable label.
    source_paths: dict[str, str]
    mtimes: dict[str, int]
    # When the picked directory was an Obsidian vault, the browser
    # supplies the vault name in `index_uploaded_files(...)` so we can
    # mint `obsidian://open?vault=<vault>&file=<source_path>` deep
    # links on every hit. None for arbitrary picked directories.
    vault_name: str | None = None
    last_used: float = field(default_factory=time_monotonic)


class WikiCorpusRegistry:
    """Process-local LRU cache of WikiCorpusAdapter + work dir per corpus_id."""

    def __init__(self, cap: int = DEFAULT_CAP) -> None:
        if cap < 1:
            raise ValueError(f"cap must be >= 1, got {cap}")
        self._cap = cap
        self._entries: OrderedDict[str, _CorpusEntry] = OrderedDict()
        self._lock = threading.Lock()

    def __contains__(self, corpus_id: str) -> bool:
        with self._lock:
            return corpus_id in self._entries

    def register(
        self,
        corpus_id: str,
        build: Callable[[], tuple[WikiRagAdapter, Path, dict[str, str], dict[str, int]]],
    ) -> str:
        """Build + insert a new corpus; evict the oldest entry at cap.

        `build` returns (adapter, work_dir, source_paths, mtimes).
        Returns the corpus_id (passed in, for fluent call sites).

        `build()` runs OUTSIDE the lock. For `dense`/`hybrid`/
        `hybrid_rerank` retrieval, it embeds every chunk (real CPU work,
        seconds to tens of seconds for a large corpus); holding the lock
        for that whole span would serialize every other registry
        operation -- `get()`, `search_with_timing()`, another `register()`
        -- behind it process-wide, freezing every OTHER session's
        index/search/qa calls until this one embedding job finishes. The
        lock only needs to protect the dict mutation below, which is fast
        regardless of retrieval mode.
        """
        adapter, work_dir, source_paths, mtimes = build()
        with self._lock:
            entry = _CorpusEntry(
                corpus_id=corpus_id,
                adapter=adapter,
                work_dir=work_dir,
                source_paths=source_paths,
                mtimes=mtimes,
            )
            self._entries[corpus_id] = entry
            self._entries.move_to_end(corpus_id)
            while len(self._entries) > self._cap:
                evicted_id, evicted = self._entries.popitem(last=False)
                _cleanup_work_dir(evicted.work_dir)
                log.info("evicted corpus_id=%s (cap=%d)", evicted_id, self._cap)
            return corpus_id

    def get(self, corpus_id: str) -> _CorpusEntry:
        with self._lock:
            if corpus_id not in self._entries:
                raise UnknownCorpusError(corpus_id)
            entry = self._entries[corpus_id]
            entry.last_used = time_monotonic()
            self._entries.move_to_end(corpus_id)
            return entry

    def touch(self, corpus_id: str) -> None:
        """Mark as recently-used without doing any other work."""
        with self._lock:
            if corpus_id in self._entries:
                self._entries[corpus_id].last_used = time_monotonic()
                self._entries.move_to_end(corpus_id)

    def remove(self, corpus_id: str) -> None:
        with self._lock:
            entry = self._entries.pop(corpus_id, None)
            if entry is not None:
                _cleanup_work_dir(entry.work_dir)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# ---- File index + search ----


def index_uploaded_files(
    files: list[dict],
    *,
    vault_name: str | None = None,
    retrieval: str | None = None,
) -> tuple[str, Path, int]:
    """Write uploaded {path, content, mtime} entries to a temp dir and
    build a WikiRagAdapter on top. `vault_name`, when supplied,
    records an Obsidian vault name on the corpus entry so every
    search hit can mint an `obsidian://` deep link for one-click
    opening in the user's vault. `retrieval` selects "tfidf" (default)
    or "bm25"; None falls back to `settings.wiki_default_retrieval`.

    Returns (corpus_id, work_dir, doc_count). The caller is responsible
    for cleanup via cleanup_corpus(corpus_id) — or letting the registry
    LRU evict it.
    """
    if retrieval is None:
        from .settings import get_settings

        retrieval = get_settings().wiki_default_retrieval
    work_dir = Path(tempfile.mkdtemp(prefix="wiki-corpus-"))
    source_paths: dict[str, str] = {}
    mtimes: dict[str, int] = {}
    for entry in files:
        rel = Path(entry["path"])
        # Defend against ../ escapes.
        if rel.is_absolute() or any(p == ".." for p in rel.parts):
            raise ValueError(f"unsafe upload path: {entry['path']!r}")
        dest = work_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(entry["content"], encoding="utf-8")
        # The ref_id WikiRagAdapter will assign for this file: flat file
        # -> stem, nested -> __-joined path with suffix stripped.
        if len(rel.parts) == 1:
            ref_id = rel.stem
        else:
            ref_id = "__".join(rel.with_suffix("").parts)
        # On collision (same stem in two dirs) we'd suffix, but that
        # would diverge from WikiRagAdapter's collision logic — easiest
        # to delegate the indexing to collect_wiki_files and recover
        # the mapping from the adapter itself.
        source_paths.setdefault(ref_id, entry["path"])
        mtimes.setdefault(ref_id, int(entry.get("mtime") or 0))

    corpus_id = uuid.uuid4().hex
    reg = get_registry()
    reg.register(
        corpus_id,
        lambda: (
            WikiRagAdapter(wiki_dir=str(work_dir), retrieval=retrieval),
            work_dir,
            source_paths,
            mtimes,
        ),
    )
    # After the adapter is built, fill in any collision-suffixed ref_ids
    # that the registry's source_paths map missed.
    entry = reg.get(corpus_id)
    for rid, path in entry.adapter._files.items():
        if rid not in entry.source_paths:
            entry.source_paths[rid] = str(
                path.relative_to(work_dir)
            )
    # ADR-0010: non-lexical modes also mint chunk ref_ids (f"{parent}#cN").
    # Attribute each chunk to its PARENT file's path/mtime -- a chunk has no
    # upload entry of its own, and without this the obsidian:// deep link
    # (below) and the "source path" UI field would fall back to the raw
    # chunk ref_id instead of a human-readable path.
    for chunk_id, chunk in entry.adapter._chunks.items():
        parent_id = chunk.parent_ref_id
        if parent_id in entry.source_paths:
            entry.source_paths.setdefault(chunk_id, entry.source_paths[parent_id])
        if parent_id in entry.mtimes:
            entry.mtimes.setdefault(chunk_id, entry.mtimes[parent_id])
    entry.vault_name = vault_name
    doc_count = len(entry.adapter._files)
    return corpus_id, work_dir, doc_count


def cleanup_corpus(corpus_id: str) -> None:
    """Remove a corpus's temp dir + drop the registry entry."""
    get_registry().remove(corpus_id)


def _cleanup_work_dir(work_dir: Path) -> None:
    """Best-effort rmrf of the temp dir."""
    try:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001 - best-effort
        log.warning("failed to remove temp work dir: %s", work_dir)


# ---- Provenance-augmented search ----


def search(corpus_id: str, query: str, top_k: int = 5) -> list[WikiSearchHit]:
    """Back-compat wrapper: returns just the hits. New callers should
    use `search_with_timing()` so per-stage latency is available for
    the /v1/wiki/metrics aggregator."""
    hits, _ = search_with_timing(corpus_id, query, top_k=top_k)
    return hits


def search_with_timing(
    corpus_id: str, query: str, top_k: int = 5,
) -> tuple[list[WikiSearchHit], dict[str, float]]:
    """Run WikiRagAdapter.search_evidence + attach provenance fields.

    AC3 fields populated:
      - source_path:    the user's relative path (e.g. 'guides/install.md')
      - evidence_span:  a substring containing the matching query terms
      - match_offsets:  (start, end) char offsets into the full document
      - coverage:       |matched_query_terms| / |query_terms|
      - contributing_terms: top-K terms by per-term TF-IDF contribution
      - mtime:          upload-time file mtime
      - obsidian_uri:    optional `obsidian://open?...` deep link
        (set when the indexed directory was an Obsidian vault — see
        `IndexFilesBody.vault_name` and the upload path in server.py)

    Returns `(hits, timing_ms)` where `timing_ms` is
    `{tokenize_ms, score_ms, sort_and_return_ms, total_ms}` for the
    dashboard's p50/p95 aggregator.
    """
    _t0 = time.monotonic()
    timing_ms: dict[str, float] = {}
    entry = get_registry().get(corpus_id)
    adapter = entry.adapter

    raw_hits = adapter.search_evidence(query, top_k=top_k)
    if not raw_hits:
        total = (time.monotonic() - _t0) * 1000.0
        timing_ms.update(
            {
                "tokenize_ms": 0.0,
                "score_ms": 0.0,
                "sort_and_return_ms": 0.0,
                "total_ms": total,
            }
        )
        return [], timing_ms

    _t_tokenize = time.monotonic()
    query_terms = set(tokenize(query))
    timing_ms["tokenize_ms"] = (time.monotonic() - _t_tokenize) * 1000.0
    if not query_terms:
        timing_ms["score_ms"] = 0.0
        timing_ms["sort_and_return_ms"] = 0.0
        timing_ms["total_ms"] = (time.monotonic() - _t0) * 1000.0
        return [], timing_ms

    out: list[WikiSearchHit] = []
    _t_score = time.monotonic()
    for r in raw_hits:
        ref_id = r.ref_id
        full_text = adapter.read_evidence(ref_id, limit=10_000)
        # Compute per-term contributions to surface "why this doc". Uses
        # whichever IDF variant the adapter's active retrieval mode
        # actually scores with (_contributing_term_weight picks TF-IDF's
        # or BM25's), so this stays accurate under either mode.
        # `term_counts()` spans both the whole-file and chunk indices
        # (ADR-0010), so this works for chunk ref_ids under dense/hybrid
        # modes too. Skip cleanly if the ref_id isn't in either index.
        contributing: list[str] = []
        doc_counts = adapter.term_counts(ref_id)
        if doc_counts is not None:
            scored_terms = sorted(
                doc_counts.items(),
                key=lambda kv: -kv[1] * adapter._contributing_term_weight(kv[0]),
            )
            contributing = [t for t, _ in scored_terms[:5]]

        # Find character offsets where query terms appear in the doc.
        # Greedy: for each query term, find all case-insensitive matches.
        offsets: list[tuple[int, int]] = []
        matched_terms: set[str] = set()
        lowered = full_text.lower()
        for term in query_terms:
            start = 0
            while True:
                idx = lowered.find(term, start)
                if idx < 0:
                    break
                offsets.append((idx, idx + len(term)))
                matched_terms.add(term)
                start = idx + len(term)

        # Build the evidence span: a ~240-char window around the densest
        # cluster of matches, so a reviewer sees context not just the
        # bare term. Falls back to the start of the doc if no matches.
        if offsets:
            span_text, span_start = _span_around_offsets(
                full_text, offsets, window=240
            )
            # Translate span offsets to be relative to the full doc.
            offsets_in_doc = [
                (s + span_start, e + span_start) for s, e in offsets
                if span_start <= s < span_start + len(span_text)
            ]
        else:
            span_text = full_text[:240]
            span_start = 0
            offsets_in_doc = []

        coverage = len(matched_terms) / len(query_terms)
        # Obsidian deep link: only when the corpus was indexed from an
        # Obsidian vault (`vault_name` set at upload time). Matches the
        # earlier wiki_ingest.py convention (path is kept verbatim,
        # .md suffix preserved).
        obsidian_uri: str | None = None
        if entry.vault_name:
            obsidian_uri = (
                f"obsidian://open?vault={entry.vault_name}"
                f"&file={entry.source_paths.get(ref_id, ref_id)}"
            )
        out.append(
            WikiSearchHit(
                ref_id=ref_id,
                title=r.title,
                score=r.score,
                source_path=entry.source_paths.get(ref_id, ref_id),
                evidence_span=span_text,
                match_offsets=offsets_in_doc,
                coverage=coverage,
                contributing_terms=contributing,
                mtime=entry.mtimes.get(ref_id, 0),
                obsidian_uri=obsidian_uri,
            )
        )
    timing_ms["score_ms"] = (time.monotonic() - _t_score) * 1000.0

    _t_sort = time.monotonic()
    out.sort(key=lambda h: -h.score)
    timing_ms["sort_and_return_ms"] = (time.monotonic() - _t_sort) * 1000.0

    timing_ms["total_ms"] = (time.monotonic() - _t0) * 1000.0
    return out, timing_ms


def _span_around_offsets(
    text: str, offsets: list[tuple[int, int]], window: int
) -> tuple[str, int]:
    """Return a window of `text` around the densest cluster of offsets.

    Returns (span_text, span_start_in_text). Used to build the
    `evidence_span` field — a substring a reviewer can read in one
    glance, instead of a hit on a single keyword buried deep in the
    document.
    """
    if not offsets:
        return text[:window], 0
    # Pick the cluster center: median offset.
    centers = sorted((s + e) // 2 for s, e in offsets)
    center = centers[len(centers) // 2]
    start = max(0, center - window // 2)
    end = min(len(text), start + window)
    # Snap to a word boundary when possible.
    if start > 0:
        ws = text.find(" ", start)
        if 0 <= ws < end:
            start = ws + 1
    if end < len(text):
        we = text.rfind(" ", start, end)
        if we > start:
            end = we
    return text[start:end], start


# ---- Singleton accessor ----


_REGISTRY: WikiCorpusRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> WikiCorpusRegistry:
    """Process-wide singleton accessor."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = WikiCorpusRegistry(cap=DEFAULT_CAP)
        return _REGISTRY


def reset_registry_for_tests() -> None:
    """Drop the singleton + clear all entries. Used by tests."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is not None:
            for cid in list(_REGISTRY._entries):
                _REGISTRY.remove(cid)
        _REGISTRY = None
