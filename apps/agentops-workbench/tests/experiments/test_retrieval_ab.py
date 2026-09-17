"""ADR-0010 step 9: the retrieval-mode A/B comparison runner.

Runs entirely offline via `--embedder fake` (a feature-hashed bag-of-words
backend, not a real model) against the real `fixtures/wiki_eval/` gold set
committed in step 8 -- this test is about the harness's plumbing (one row
per mode, a stable per-query schema, correct artifact files), not about
producing a meaningful retrieval-quality number.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentops_workbench.experiments.retrieval_ab import (
    ALL_MODES,
    _hash_embedding_backend,
    run_comparison,
    write_artifacts,
)

WIKI_EVAL_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "wiki_eval"


def test_run_comparison_produces_one_summary_per_mode() -> None:
    embedder = _hash_embedding_backend()
    result = run_comparison(
        WIKI_EVAL_DIR, split="dev", k=5, modes=ALL_MODES, embedder=embedder,
    )
    assert {s.mode for s in result.summaries} == set(ALL_MODES)
    for s in result.summaries:
        assert s.n_queries > 0


def test_run_comparison_per_query_rows_cover_every_mode_and_query() -> None:
    embedder = _hash_embedding_backend()
    from agentops_workbench.benchmark.wiki_eval_load import load_split

    queries = load_split(WIKI_EVAL_DIR, "dev")
    result = run_comparison(
        WIKI_EVAL_DIR, split="dev", k=5, modes=["tfidf", "bm25"], embedder=embedder,
    )
    assert len(result.per_query) == 2 * len(queries)
    seen = {(r.mode, r.query_id) for r in result.per_query}
    assert seen == {(m, q.id) for m in ("tfidf", "bm25") for q in queries}


def test_no_answer_family_scores_metrics_as_1_when_nothing_relevant_exists() -> None:
    """A no_answer query has empty gold; every binary metric's empty-gold
    convention says a mode that returns nothing (or returns something,
    for precision) is scored per the documented convention -- not an error."""
    embedder = _hash_embedding_backend()
    result = run_comparison(
        WIKI_EVAL_DIR, split="dev", k=5, modes=["bm25"], embedder=embedder,
    )
    no_answer_rows = [r for r in result.per_query if r.family_id == "no_answer"]
    assert no_answer_rows
    for r in no_answer_rows:
        assert r.recall_at_k == 1.0
        assert r.ndcg_at_k == 1.0


def test_lexical_modes_never_construct_the_injected_embedder(tmp_path: Path) -> None:
    """The embedder is passed to every mode's adapter build call, but
    WikiRagAdapter itself must ignore it for tfidf/bm25 -- assert the
    comparison runner doesn't break that contract by, say, embedding
    documents itself before construction."""
    calls: list[str] = []

    class _CountingEmbedder:
        dim = 4

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            calls.append("embed_documents")
            return [[0.0] * 4 for _ in texts]

        def embed_query(self, text: str) -> list[float]:
            calls.append("embed_query")
            return [0.0] * 4

    run_comparison(
        WIKI_EVAL_DIR, split="dev", k=5, modes=["tfidf", "bm25"], embedder=_CountingEmbedder(),
    )
    assert calls == []


def test_write_artifacts_creates_manifest_report_and_per_query_files(tmp_path: Path) -> None:
    embedder = _hash_embedding_backend()
    result = run_comparison(
        WIKI_EVAL_DIR, split="dev", k=5, modes=["tfidf", "bm25"], embedder=embedder,
    )
    out_dir = tmp_path / "retrieval-ab-v1"
    write_artifacts(out_dir, result, split="dev", k=5, modes=["tfidf", "bm25"])

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["split"] == "dev"
    assert manifest["k"] == 5
    assert manifest["modes"] == ["tfidf", "bm25"]

    lines = (out_dir / "per_query.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(result.per_query)
    row = json.loads(lines[0])
    assert {"mode", "query_id", "family_id", "ranked_refs", "recall_at_k", "ndcg_at_k"} <= set(row)

    report = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "tfidf" in report and "bm25" in report
    assert "delta" in report.lower()


def test_held_out_split_refuses_without_confirm_flag() -> None:
    from agentops_workbench.experiments.retrieval_ab import main

    with pytest.raises(SystemExit):
        main(["--split", "held_out", "--wiki-eval-dir", str(WIKI_EVAL_DIR), "--embedder", "fake"])


def test_held_out_split_runs_with_confirm_flag(tmp_path: Path) -> None:
    from agentops_workbench.experiments.retrieval_ab import main

    main([
        "--split", "held_out", "--confirm-held-out",
        "--wiki-eval-dir", str(WIKI_EVAL_DIR), "--embedder", "fake",
        "--out-dir", str(tmp_path / "out"), "--modes", "tfidf,bm25",
    ])
    assert (tmp_path / "out" / "report.md").exists()
