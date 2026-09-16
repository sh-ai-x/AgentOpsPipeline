"""TDD: wiki_corpus.py registry, file-index round-trip, LRU eviction."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentops_workbench import wiki_corpus
from agentops_workbench.wiki_corpus import (
    WikiCorpusRegistry,
    WikiSearchHit,
    index_uploaded_files,
)


@pytest.fixture
def sample_files() -> list[dict]:
    """Three .md files at synthetic paths inside a fictional user dir."""
    return [
        {
            "path": "guides/install.md",
            "content": (
                "# Install\n"
                "Install LangGraph with PostgreSQL checkpointing.\n"
                "Use pip install langgraph[postgres].\n"
            ),
            "mtime": 1_700_000_000_000,
        },
        {
            "path": "guides/auth.md",
            "content": (
                "# Auth\n"
                "JWT with HS256, generate a 48-byte secret.\n"
                "Set AGENTOPS_JWT_SECRET in .env.\n"
            ),
            "mtime": 1_700_000_001_000,
        },
        {
            "path": "top.md",
            "content": (
                "# Top\n"
                "Welcome to the workspace. Top-level overview.\n"
            ),
            "mtime": 1_700_000_002_000,
        },
    ]


# ---- Pure-function helpers ----


def test_extract_citation_refs_parses_bracketed_tokens() -> None:
    text = "LangGraph is fast [wiki__langgraph] and supports JWT [auth]."
    refs = wiki_corpus.extract_citation_refs(text)
    assert refs == ["wiki__langgraph", "auth"]


def test_extract_citation_refs_ignores_unclosed_brackets() -> None:
    text = "Trailing bracket [unclosed with no second bracket."
    assert wiki_corpus.extract_citation_refs(text) == []


def test_extract_citation_refs_deduplicates_preserving_order() -> None:
    text = "First [a] then [b] and again [a]."
    assert wiki_corpus.extract_citation_refs(text) == ["a", "b"]


def test_split_sentences_handles_abbreviations_and_decimal_points() -> None:
    # Period after 'e.g.' is NOT a sentence boundary.
    text = (
        "Use Postgres for durable state, e.g. via PostgresSaver. "
        "MemorySaver is for tests only."
    )
    sents = wiki_corpus.split_sentences(text)
    assert len(sents) == 2
    assert "PostgresSaver" in sents[0]
    assert "MemorySaver" in sents[1]


def test_tokenize_matches_wikirag_token_pattern() -> None:
    # WikiRagAdapter uses _TOKEN_RE = re.compile(r\"[a-z0-9]+\") so we mirror it.
    toks = wiki_corpus.tokenize("LangGraph Checkpointing 1.2 alpha")
    assert toks == ["langgraph", "checkpointing", "1", "2", "alpha"]


# ---- File index round-trip ----


def test_index_uploaded_files_writes_to_temp_dir_and_returns_corpus_id(
    tmp_path: Path, sample_files: list[dict]
) -> None:
    corpus_id, work_dir, doc_count = index_uploaded_files(sample_files)
    try:
        assert isinstance(corpus_id, str) and len(corpus_id) >= 16
        assert work_dir.is_dir()
        assert doc_count == 3
        # Files landed under work_dir at their relative paths.
        assert (work_dir / "guides" / "install.md").exists()
        assert (work_dir / "top.md").exists()
    finally:
        wiki_corpus.cleanup_corpus(corpus_id)


def test_index_uploaded_files_preserves_path_encoding_for_nested_files(
    tmp_path: Path, sample_files: list[dict]
) -> None:
    corpus_id, _, _ = index_uploaded_files(sample_files)
    try:
        entry = wiki_corpus.get_registry().get(corpus_id)
        adapter = entry.adapter
        # Flat file uses stem as ref_id.
        assert "top" in adapter._files
        # Nested file uses path-encoded ref_id (guides__install).
        assert "guides__install" in adapter._files
        assert "guides__auth" in adapter._files
    finally:
        wiki_corpus.cleanup_corpus(corpus_id)


# ---- Search with provenance fields ----


def test_search_returns_provenance_fields(tmp_path: Path, sample_files: list[dict]) -> None:
    corpus_id, _, _ = index_uploaded_files(sample_files)
    try:
        # Tokenizer is `[a-z0-9]+` (no camelCase split), so "PostgresSaver"
        # becomes one token "postgressaver". Use a query that matches
        # tokens actually present in the doc body.
        hits = wiki_corpus.search(corpus_id, "postgres checkpointing", top_k=5)
        assert hits, "expected at least one hit"
        hit = hits[0]
        assert isinstance(hit, WikiSearchHit)
        assert hit.ref_id == "guides__install"
        # Provenance fields (AC3).
        assert hit.source_path == "guides/install.md"
        assert hit.mtime == 1_700_000_000_000
        assert 0.0 < hit.score <= 1.0
        assert 0.0 < hit.coverage <= 1.0
        # Coverage must reflect the matched fraction of query terms.
        # query terms = {postgres, checkpointing} = 2; doc has both -> 1.0.
        assert hit.coverage == pytest.approx(1.0, abs=0.01)
        # Either tokenization form of the query term may appear in the
        # contributing-terms list (the doc has "PostgreSQL" and "postgres").
        assert any("postgres" in t for t in hit.contributing_terms)
        # Evidence span must contain the matching term.
        assert "postgres" in hit.evidence_span.lower()
        # Span offsets must be valid against the full document text.
        adapter = wiki_corpus.get_registry().get(corpus_id).adapter
        full = adapter.read_evidence(hit.ref_id, limit=10_000)
        for start, end in hit.match_offsets:
            assert 0 <= start < end <= len(full), (
                f"span offsets out of range: {start}-{end} doc_len={len(full)}"
            )
            assert full[start:end].strip() != ""
    finally:
        wiki_corpus.cleanup_corpus(corpus_id)


def test_search_returns_empty_for_unknown_corpus() -> None:
    with pytest.raises(wiki_corpus.UnknownCorpusError):
        wiki_corpus.search("nonexistent-id", "any query", top_k=5)


def test_search_filters_to_top_k(tmp_path: Path, sample_files: list[dict]) -> None:
    corpus_id, _, _ = index_uploaded_files(sample_files)
    try:
        hits = wiki_corpus.search(corpus_id, "the", top_k=2)
        assert len(hits) <= 2
    finally:
        wiki_corpus.cleanup_corpus(corpus_id)


# ---- Registry + LRU eviction ----


def test_registry_lru_eviction_when_cap_exceeded(tmp_path: Path) -> None:
    """Creating corpora beyond the cap evicts the least-recently-used one."""
    reg = WikiCorpusRegistry(cap=2)

    def _build_stub() -> tuple:
        # The real WikiRagAdapter + work_dir; here we only need the
        # registry's LRU bookkeeping to fire, so a tiny dummy works.
        from agentops_workbench.adapters.wiki_rag import WikiRagAdapter

        work = tmp_path / "stub-wiki"
        work.mkdir(exist_ok=True)
        (work / "stub.md").write_text("stub", encoding="utf-8")
        adapter = WikiRagAdapter(wiki_dir=str(work))
        return adapter, work, {"stub": "stub.md"}, {"stub": 0}

    reg.register("a", _build_stub)
    reg.register("b", _build_stub)
    reg.register("c", _build_stub)
    # At cap=2 with 3 inserts, the first (oldest) entry is evicted.
    assert "a" not in reg, "oldest entry should be evicted at cap=2"
    assert "b" in reg
    assert "c" in reg


def test_registry_touch_updates_lru_order(tmp_path: Path) -> None:
    reg = WikiCorpusRegistry(cap=2)

    def _build_stub() -> tuple:
        from agentops_workbench.adapters.wiki_rag import WikiRagAdapter

        work = tmp_path / "stub-wiki"
        work.mkdir(exist_ok=True)
        (work / "stub.md").write_text("stub", encoding="utf-8")
        adapter = WikiRagAdapter(wiki_dir=str(work))
        return adapter, work, {"stub": "stub.md"}, {"stub": 0}

    reg.register("a", _build_stub)
    reg.register("b", _build_stub)
    # Touch a so it becomes most-recently-used; c registration should
    # now evict b, not a.
    reg.touch("a")
    reg.register("c", _build_stub)
    assert "a" in reg
    assert "b" not in reg
    assert "c" in reg


def test_registry_remove(tmp_path: Path) -> None:
    reg = WikiCorpusRegistry(cap=4)

    def _build_stub() -> tuple:
        from agentops_workbench.adapters.wiki_rag import WikiRagAdapter

        work = tmp_path / "stub-wiki"
        work.mkdir(exist_ok=True)
        (work / "stub.md").write_text("stub", encoding="utf-8")
        adapter = WikiRagAdapter(wiki_dir=str(work))
        return adapter, work, {"stub": "stub.md"}, {"stub": 0}

    reg.register("a", _build_stub)
    reg.remove("a")
    assert "a" not in reg


def test_registry_get_raises_for_unknown() -> None:
    reg = WikiCorpusRegistry(cap=4)
    with pytest.raises(KeyError):
        reg.get("nope")


# ---- Cleanup ----


def test_cleanup_corpus_removes_files_and_registry_entry(tmp_path: Path) -> None:
    corpus_id, work_dir, _ = index_uploaded_files([
        {"path": "x.md", "content": "hi", "mtime": 0}
    ])
    wiki_corpus.cleanup_corpus(corpus_id)
    assert not work_dir.exists(), "temp dir should be removed"
    with pytest.raises(wiki_corpus.UnknownCorpusError):
        wiki_corpus.search(corpus_id, "hi", top_k=5)


def test_get_registry_is_singleton() -> None:
    r1 = wiki_corpus.get_registry()
    r2 = wiki_corpus.get_registry()
    assert r1 is r2, "registry must be process-singleton"
