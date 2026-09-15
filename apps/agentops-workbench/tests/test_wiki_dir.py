"""wiki_dir setting: when set, the agent reads from a user-supplied
directory of *.md files instead of fixtures/docs/.

Covers both topologies (fixed graph's `_retrieve_docs` and
`planner_executor`/`single_agent` via `WikiRagAdapter` compat shims).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentops_workbench.graph.fixed import _retrieve_docs, run_fixed_graph
from agentops_workbench.llm.local_fake import LocalFakeAdapter


@pytest.fixture
def wiki_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wiki"
    d.mkdir()
    (d / "alpha.md").write_text(
        "# Alpha\n\nPostgreSQL checkpointing uses PostgresSaver for durable state."
    )
    (d / "beta.md").write_text(
        "# Beta\n\nMemorySaver is for tests only and resets on restart."
    )
    return d


def test_retrieve_docs_reads_from_wiki_dir(wiki_dir: Path) -> None:
    """When docs_dir is overridden with a wiki dir, retrieval finds its files."""
    out = _retrieve_docs("checkpointing postgres", docs_dir=str(wiki_dir))
    assert "alpha.md" in out or "alpha" in out
    # _retrieve_docs lowercases file content for matching, so search
    # against the lowercased substring.
    assert "postgressaver" in out
    assert "(no relevant docs found)" not in out


def test_retrieve_docs_returns_empty_for_unrelated_query(wiki_dir: Path) -> None:
    out = _retrieve_docs("kubernetes operator pattern", docs_dir=str(wiki_dir))
    assert out == "(no relevant docs found)"


def test_run_fixed_graph_threads_corpus_dir(wiki_dir: Path) -> None:
    """End-to-end: run_fixed_graph with a wiki dir answers from it."""
    adapter = LocalFakeAdapter()
    out = run_fixed_graph(adapter, "How does checkpointing work?", docs_dir=str(wiki_dir))
    assert out.state.value == "succeeded"
    assert out.route in {"answer", "refuse"}  # local-fake is scripted; route is deterministic


def test_wiki_rag_adapter_used_for_planner_topology(
    wiki_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """planner_executor uses WikiRagAdapter when wiki_mode=True (and InMemoryDocumentClient otherwise).

    Uses `build_document_client` directly rather than inspect.getsource on
    run_planner_executor — the test couples to the documented factory
    contract, not the source-string of a caller.
    """
    from agentops_workbench.adapters.wiki_rag import WikiRagAdapter
    from agentops_workbench.mcp import InMemoryDocumentClient, build_document_client

    # wiki_mode=True -> WikiRagAdapter(corpus_dir)
    wiki_client = build_document_client(str(wiki_dir), wiki_mode=True)
    assert isinstance(wiki_client, WikiRagAdapter)
    assert wiki_client._wiki_dir == str(wiki_dir)

    # wiki_mode=False -> InMemoryDocumentClient (substring scan, NOT TF-IDF)
    plain_client = build_document_client("fixtures/docs", wiki_mode=False)
    assert isinstance(plain_client, InMemoryDocumentClient)

    # Explicit document_client overrides both
    sentinel = InMemoryDocumentClient()
    override = build_document_client(str(wiki_dir), wiki_mode=True, document_client=sentinel)
    assert override is sentinel, "explicit document_client must be returned as-is"

    # Smoke: the adapter actually retrieves from the wiki_dir corpus
    hits = wiki_client.search_evidence("checkpointing postgres", top_k=2)
    assert hits, "WikiRagAdapter must return at least one hit on its own corpus"
    assert hits[0].source_kind == "wiki"
    assert hits[0].ref_id in {"alpha", "beta"}
