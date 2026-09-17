"""Non-regression instrument for ADR-0010 (dense/hybrid/rerank retrieval).

These two tests are the enforcement mechanism, not documentation: they make
"tfidf and bm25 stay byte-identical" a fact a future diff cannot violate
without a test failure, rather than a claim in a docstring.

`test_lexical_scores_are_frozen` pins the exact float score WikiRagAdapter
returns for a fixed query set over a fixed corpus, for both lexical modes,
generated once against the pre-ADR-0010 code and hard-coded here. Any change
to `_score`/`_cosine_score`/`_bm25_score`/`_idf`/`_bm25_idf` that alters a
lexical result by so much as a rounding error fails this test.

`test_lexical_modes_never_import_heavy_deps` proves the "additive, zero cost
unless opted in" property: constructing and querying a tfidf/bm25 adapter
must never pull `fastembed` or `onnxruntime` into the process, even when
those packages are installed (a deployment running only `[dev]` doesn't have
them at all, so this also passes there -- the assertion is exercised either
way).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentops_workbench.adapters.wiki_rag import WikiRagAdapter

_QUERIES = [
    "checkpointing persistence",
    "postgres",
    "rate limits",
    "onboarding laptop",
    "429 response",
    "durable execution",
]

# Generated once via `WikiRagAdapter(wiki_dir=..., retrieval=mode).search_evidence(q, top_k=5)`
# over the corpus built by `_make_lexical_wiki` below, immediately before ADR-0010's
# production changes landed. Frozen to rel=1e-12 -- see module docstring.
_FROZEN_SCORES: dict[str, dict[str, list[tuple[str, float]]]] = {
    "tfidf": {
        "checkpointing persistence": [("checkpointing", 0.38759954610643116)],
        "postgres": [("checkpointing", 0.16745362869237942)],
        "rate limits": [("rate-limits", 0.4298997884680694)],
        "onboarding laptop": [("onboarding", 0.17505468002283647)],
        "429 response": [("rate-limits", 0.28659985897871293)],
        "durable execution": [("checkpointing", 0.23681519276535146)],
    },
    "bm25": {
        "checkpointing persistence": [("checkpointing", 1.7132388698894785)],
        "postgres": [("checkpointing", 0.8998433513869049)],
        "rate limits": [("rate-limits", 2.2591742484935025)],
        "onboarding laptop": [("onboarding", 1.1613694061495146)],
        "429 response": [("rate-limits", 1.8411470619674044)],
        "durable execution": [("checkpointing", 1.7996867027738097)],
    },
}


def _make_lexical_wiki(tmp_path: Path) -> Path:
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "checkpointing.md").write_text(
        "LangGraph checkpointing persists graph state between steps. "
        "The PostgresCheckpointer writes checkpoint state to Postgres. "
        "Checkpointing checkpointing checkpointing is central to durable execution.",
        encoding="utf-8",
    )
    (wiki_dir / "rate-limits.md").write_text(
        "Rate limits govern how many requests a client may issue per minute. "
        "A 429 response means the rate limit was exceeded.",
        encoding="utf-8",
    )
    (wiki_dir / "onboarding.md").write_text(
        "Welcome to the team. This page covers laptop setup and VPN access.",
        encoding="utf-8",
    )
    return wiki_dir


@pytest.mark.parametrize("mode", ["tfidf", "bm25"])
def test_lexical_scores_are_frozen(tmp_path: Path, mode: str) -> None:
    wiki_dir = _make_lexical_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval=mode)

    for query, expected in _FROZEN_SCORES[mode].items():
        results = adapter.search_evidence(query, top_k=1)
        actual = [(r.ref_id, r.score) for r in results]
        assert len(actual) == len(expected), f"mode={mode} query={query!r}"
        for (got_id, got_score), (want_id, want_score) in zip(actual, expected, strict=True):
            assert got_id == want_id, f"mode={mode} query={query!r}"
            assert got_score == pytest.approx(want_score, rel=1e-12), (
                f"mode={mode} query={query!r} score drifted from the frozen "
                f"golden value -- a lexical-mode change is not additive"
            )


def test_lexical_modes_never_import_heavy_deps(tmp_path: Path) -> None:
    wiki_dir = _make_lexical_wiki(tmp_path)
    for mode in ("tfidf", "bm25"):
        adapter = WikiRagAdapter(wiki_dir=str(wiki_dir), retrieval=mode)
        adapter.search_evidence("checkpointing persistence", top_k=5)
        adapter.read_evidence(next(iter(adapter._files)))
    assert "fastembed" not in sys.modules
    assert "onnxruntime" not in sys.modules
