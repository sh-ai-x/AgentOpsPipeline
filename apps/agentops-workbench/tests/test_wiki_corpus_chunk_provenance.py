"""ADR-0010 step 5: chunk ref_ids must inherit their parent file's provenance.

Uses a fake embedder (monkeypatched in place of the real fastembed-backed
default) so this stays offline and independent of ADR-0010 step 10.
"""
from __future__ import annotations

import pytest

from agentops_workbench import wiki_corpus
from agentops_workbench.wiki_corpus import get_registry, index_uploaded_files
from tests.adapters._fakes import FakeEmbeddingBackend


@pytest.fixture(autouse=True)
def _fake_dense_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = FakeEmbeddingBackend(
        keyword_vectors={"install": [1.0, 0.0], "auth": [0.0, 1.0], "jwt": [0.0, 1.0]}
    )
    monkeypatch.setattr(
        "agentops_workbench.adapters.wiki_rag._default_embedding_backend",
        lambda: embedder,
    )
    wiki_corpus.reset_registry_for_tests()
    yield
    wiki_corpus.reset_registry_for_tests()


@pytest.fixture
def sample_files() -> list[dict]:
    return [
        {
            "path": "guides/install.md",
            "content": "# Install\nInstall LangGraph with PostgreSQL checkpointing.\n",
            "mtime": 1_700_000_000_000,
        },
        {
            "path": "guides/auth.md",
            "content": "# Auth\nJWT with HS256, generate a 48-byte secret.\n",
            "mtime": 1_700_000_001_000,
        },
    ]


def test_chunk_ref_ids_inherit_parent_source_path_and_mtime(sample_files: list[dict]) -> None:
    corpus_id, _, _ = index_uploaded_files(sample_files, retrieval="dense")
    entry = get_registry().get(corpus_id)

    assert entry.adapter._chunks, "expected dense mode to produce chunk ref_ids"
    for chunk_id, chunk in entry.adapter._chunks.items():
        assert chunk_id in entry.source_paths
        assert entry.source_paths[chunk_id] == entry.source_paths[chunk.parent_ref_id]
        assert entry.mtimes[chunk_id] == entry.mtimes[chunk.parent_ref_id]


def test_search_with_timing_reports_the_parent_path_for_a_chunk_hit(
    sample_files: list[dict],
) -> None:
    corpus_id, _, _ = index_uploaded_files(sample_files, retrieval="dense")
    hits, _timing = wiki_corpus.search_with_timing(corpus_id, "install", top_k=5)

    assert hits, "expected at least one chunk hit"
    assert hits[0].ref_id.startswith("install#c") or "install" in hits[0].ref_id
    assert hits[0].source_path == "guides/install.md"


def test_lexical_mode_search_hit_shape_is_unchanged(sample_files: list[dict]) -> None:
    """Non-regression: a tfidf-mode WikiSearchHit.to_dict() keeps its exact
    shape and field set now that chunk modes exist alongside it."""
    corpus_id, _, _ = index_uploaded_files(sample_files, retrieval="tfidf")
    hits, _timing = wiki_corpus.search_with_timing(corpus_id, "install postgresql", top_k=5)
    assert hits
    payload = hits[0].to_dict()
    assert set(payload) == {
        "ref_id", "title", "score", "source_path", "evidence_span",
        "match_offsets", "coverage", "contributing_terms", "mtime", "obsidian_uri",
    }
    assert payload["ref_id"] == "guides__install"
    assert payload["source_path"] == "guides/install.md"
