"""ADR-0010 steps 4/6/7: dense, hybrid and hybrid_rerank retrieval modes.

All tests inject a fake embedder/reranker (`_fakes.py`) -- no network, no
real model, fully deterministic. Real-backend wiring (`fastembed`) is
exercised separately once installed (ADR-0010 step 10), not here.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from _fakes import FakeEmbeddingBackend, FakeRerankBackend

from agentops_workbench.adapters.base import EvidenceRef
from agentops_workbench.adapters.wiki_rag import MAX_WIKI_CHUNKS, WikiRagAdapter
from agentops_workbench.mcp import MCPError


def _synonym_wiki(tmp_path: Path) -> Path:
    """Two notes sharing NO vocabulary with the query -- only a dense/semantic
    leg can find the right one; lexical modes must fail here."""
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "resume-runs.md").write_text(
        "# Resuming interrupted runs\n\n"
        "If the process dies mid-run, restart it and it will pick up where "
        "it left off using the last saved checkpoint.\n",
        encoding="utf-8",
    )
    (wiki_dir / "onboarding.md").write_text(
        "# Onboarding\n\nWelcome to the team. Set up your laptop and VPN.\n",
        encoding="utf-8",
    )
    return wiki_dir


def _embedder() -> FakeEmbeddingBackend:
    # "resume" (query) and "restart"/"pick up" (document) share no tokens,
    # but both map to the same fake semantic direction -- this is the
    # relationship a real embedding model is expected to capture.
    return FakeEmbeddingBackend(
        keyword_vectors={
            "resume": [1.0, 0.0],
            "restart": [1.0, 0.0],
            "pick up": [1.0, 0.0],
            "onboarding": [0.0, 1.0],
            "laptop": [0.0, 1.0],
        }
    )


def test_dense_mode_finds_a_synonym_match_lexical_modes_would_miss(tmp_path: Path) -> None:
    wiki_dir = _synonym_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval="dense", embedder=_embedder())

    # No lexical overlap with "resume-runs.md" at all (query says "resume
    # after a crash"; the note says "restart"/"pick up").
    results = adapter.search_evidence("how do I resume after a crash", top_k=5)

    assert results, "dense mode returned nothing for a synonym query"
    assert results[0].ref_id.startswith("resume-runs#c")
    assert isinstance(results[0], EvidenceRef)
    assert results[0].source_kind == "wiki"


def test_dense_mode_returns_empty_for_a_query_with_no_semantic_match(tmp_path: Path) -> None:
    wiki_dir = _synonym_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval="dense", embedder=_embedder())

    # Shares no keyword with either note -- must embed to the zero vector,
    # which has cosine similarity 0.0 with everything and must not pass the
    # _DENSE_MIN_COSINE floor. This is the refusal-path safety property.
    results = adapter.search_evidence("zzz-nonexistent-gibberish-zzz", top_k=5)
    assert results == []


def test_dense_ref_id_format_is_parent_hash_c_n(tmp_path: Path) -> None:
    wiki_dir = _synonym_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval="dense", embedder=_embedder())
    results = adapter.search_evidence("resume", top_k=5)
    for r in results:
        assert "#c" in r.ref_id
        parent, _, suffix = r.ref_id.partition("#c")
        assert suffix.isdigit()
        assert parent in {"resume-runs", "onboarding"}


def test_read_evidence_resolves_a_chunk_ref_id_to_its_raw_source_span(tmp_path: Path) -> None:
    wiki_dir = _synonym_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval="dense", embedder=_embedder())
    results = adapter.search_evidence("resume", top_k=1)
    assert results
    text = adapter.read_evidence(results[0].ref_id)
    # The raw span is literal file content -- not the heading-prefixed
    # embedding text search/embed_documents actually saw.
    full = (wiki_dir / "resume-runs.md").read_text(encoding="utf-8")
    assert text in full


def test_max_wiki_chunks_raises_unsupported_capability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wiki_dir = _synonym_wiki(tmp_path)
    monkeypatch.setattr("agentops_workbench.adapters.wiki_rag.MAX_WIKI_CHUNKS", 1)
    with pytest.raises(MCPError):
        WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval="dense", embedder=_embedder())


def test_max_wiki_chunks_constant_is_a_generous_default() -> None:
    assert MAX_WIKI_CHUNKS >= 1000


# ---- hybrid ----


def _hybrid_wiki(tmp_path: Path) -> Path:
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "checkpointing.md").write_text(
        "# Checkpointing\n\nPostgresCheckpointer persists graph state to Postgres.\n",
        encoding="utf-8",
    )
    (wiki_dir / "resume-runs.md").write_text(
        "# Resuming\n\nRestart the process and it picks up from the last save.\n",
        encoding="utf-8",
    )
    (wiki_dir / "unrelated.md").write_text(
        "# Unrelated\n\nThis page is about lunch options near the office.\n",
        encoding="utf-8",
    )
    return wiki_dir


def test_hybrid_mode_combines_a_lexical_hit_and_a_semantic_hit(tmp_path: Path) -> None:
    wiki_dir = _hybrid_wiki(tmp_path)
    embedder = FakeEmbeddingBackend(
        keyword_vectors={
            "restart": [1.0, 0.0],
            "resume": [1.0, 0.0],
            "checkpointing": [0.0, 1.0],
            "postgres": [0.0, 1.0],
        }
    )
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval="hybrid", embedder=embedder)

    # "checkpointing" is a direct lexical hit on checkpointing.md AND a
    # semantic hit via the fake embedder -- both legs should agree.
    lexical_and_semantic = adapter.search_evidence("checkpointing", top_k=5)
    assert any(r.ref_id.startswith("checkpointing#c") for r in lexical_and_semantic)

    # "resume" has zero lexical overlap with resume-runs.md ("restart"), so
    # only the dense leg can surface it; hybrid must still find it.
    semantic_only = adapter.search_evidence("resume", top_k=5)
    assert any(r.ref_id.startswith("resume-runs#c") for r in semantic_only)
    assert all(not r.ref_id.startswith("unrelated#c") for r in semantic_only)


def test_hybrid_rrf_fusion_matches_a_hand_computed_two_leg_example() -> None:
    from agentops_workbench.adapters.wiki_rag import WikiRagAdapter as _Adapter

    dense_ranked = [("a", 0.9), ("b", 0.5), ("c", 0.1)]
    bm25_ranked = [("b", 5.0), ("a", 2.0)]
    fused = _Adapter._rrf_fuse(None, dense_ranked, bm25_ranked)  # type: ignore[arg-type]
    fused_map = dict(fused)

    k = 60
    expected_a = 1.0 / (k + 1) + 1.0 / (k + 2)  # rank 0 in dense, rank 1 in bm25
    expected_b = 1.0 / (k + 2) + 1.0 / (k + 1)  # rank 1 in dense, rank 0 in bm25
    expected_c = 1.0 / (k + 3)                  # rank 2 in dense only

    assert fused_map["a"] == pytest.approx(expected_a)
    assert fused_map["b"] == pytest.approx(expected_b)
    assert fused_map["c"] == pytest.approx(expected_c)
    # a and b tie exactly (symmetric ranks); c is strictly last.
    assert fused_map["a"] == pytest.approx(fused_map["b"])
    assert fused_map["c"] < fused_map["a"]


# ---- hybrid_rerank ----


def test_hybrid_rerank_reorders_using_the_injected_reranker(tmp_path: Path) -> None:
    wiki_dir = _hybrid_wiki(tmp_path)
    embedder = FakeEmbeddingBackend(
        keyword_vectors={
            "restart": [1.0, 0.0],
            "resume": [1.0, 0.0],
            "checkpointing": [0.0, 1.0],
            "postgres": [0.0, 1.0],
        }
    )
    # Script the reranker to strongly prefer the resume-runs chunk over
    # whatever RRF ranked first, proving the rerank stage actually changes
    # the final order rather than passing hybrid's order through.
    reranker = FakeRerankBackend(
        score_fn=lambda q, d: 10.0 if "restart" in d.lower() else 0.0
    )
    adapter = WikiRagAdapter(
        wiki_dir=str(wiki_dir), retrieval="hybrid_rerank", embedder=embedder, reranker=reranker
    )

    results = adapter.search_evidence("checkpointing resume", top_k=5)
    assert results
    assert results[0].ref_id.startswith("resume-runs#c")
    assert reranker.calls, "reranker was never invoked"


def test_hybrid_rerank_only_sends_the_top_rerank_candidates_count(tmp_path: Path) -> None:
    from agentops_workbench.adapters import wiki_rag as wiki_rag_mod

    wiki_dir = _hybrid_wiki(tmp_path)
    embedder = FakeEmbeddingBackend(keyword_vectors={"checkpointing": [1.0], "postgres": [1.0]})
    reranker = FakeRerankBackend()
    adapter = WikiRagAdapter(
        wiki_dir=str(wiki_dir), retrieval="hybrid_rerank", embedder=embedder, reranker=reranker
    )
    adapter.search_evidence("checkpointing", top_k=5)
    assert reranker.calls
    _, docs_sent = reranker.calls[0]
    assert len(docs_sent) <= wiki_rag_mod._RERANK_CANDIDATES


def test_reranker_is_not_constructed_for_non_rerank_modes(tmp_path: Path) -> None:
    wiki_dir = _hybrid_wiki(tmp_path)
    embedder = FakeEmbeddingBackend(keyword_vectors={"checkpointing": [1.0]})
    for mode in ("dense", "hybrid"):
        adapter = WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval=mode, embedder=embedder)
        adapter.search_evidence("checkpointing", top_k=5)
        assert adapter._reranker is None, f"mode={mode} constructed a reranker it never needed"


def test_lexical_modes_are_unaffected_by_the_new_optional_params(tmp_path: Path) -> None:
    """Constructing a lexical-mode adapter never touches chunk/dense state."""
    wiki_dir = _hybrid_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval="bm25")
    assert adapter._chunks == {}
    results = adapter.search_evidence("checkpointing", top_k=5)
    assert results and results[0].ref_id == "checkpointing"  # whole-file ref_id, no "#c"
