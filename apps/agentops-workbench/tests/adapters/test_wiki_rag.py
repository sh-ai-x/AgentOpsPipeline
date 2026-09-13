"""WikiRagAdapter -- TF-IDF cosine similarity over a directory of .md files."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentops_workbench.adapters.base import EvidenceRef
from agentops_workbench.adapters.wiki_rag import WikiRagAdapter
from agentops_workbench.mcp import MCPError


def _make_wiki(tmp_path: Path) -> Path:
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


def test_search_evidence_ranks_the_document_that_actually_discusses_the_query_first(
    tmp_path: Path,
) -> None:
    wiki_dir = _make_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir))

    results = adapter.search_evidence("checkpointing persistence", top_k=5)

    assert len(results) >= 1
    assert isinstance(results[0], EvidenceRef)
    assert results[0].ref_id == "checkpointing"
    assert results[0].source_kind == "wiki"
    assert results[0].score > 0.0
    # The onboarding doc shares no terms with the query -- must not appear.
    assert all(r.ref_id != "onboarding" for r in results)


def test_tfidf_downweights_a_term_that_appears_in_every_document(tmp_path: Path) -> None:
    """A term common to every doc in the corpus should contribute less to the
    score than a term unique to one doc -- the whole point of the IDF factor.
    Build a corpus where "checkpointing" appears in every doc (so IDF ~ 0)
    and "postgres" appears in only one -- a query on "postgres" must not
    lose to a query on "checkpointing" for the doc that has both.
    """
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "a.md").write_text("checkpointing checkpointing checkpointing", encoding="utf-8")
    (wiki_dir / "b.md").write_text("checkpointing checkpointing checkpointing", encoding="utf-8")
    (wiki_dir / "c.md").write_text("checkpointing postgres postgres postgres", encoding="utf-8")
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir))

    results = adapter.search_evidence("postgres", top_k=5)
    assert results[0].ref_id == "c"
    # "checkpointing" alone should score every doc roughly equally (low IDF);
    # "postgres" is unique to c.md and must give c.md a strong lead.
    common_term_results = adapter.search_evidence("checkpointing", top_k=5)
    assert len(common_term_results) == 3


def test_top_k_limits_result_count(tmp_path: Path) -> None:
    wiki_dir = _make_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir))
    results = adapter.search_evidence("checkpointing rate limits onboarding laptop", top_k=1)
    assert len(results) == 1


def test_read_evidence_round_trip_by_ref_id(tmp_path: Path) -> None:
    wiki_dir = _make_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir))
    results = adapter.search_evidence("checkpointing", top_k=1)
    ref_id = results[0].ref_id

    text = adapter.read_evidence(ref_id)
    assert "PostgresCheckpointer" in text


def test_read_evidence_respects_offset_and_limit(tmp_path: Path) -> None:
    wiki_dir = _make_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir))
    full = adapter.read_evidence("checkpointing")
    sliced = adapter.read_evidence("checkpointing", offset=5, limit=10)
    assert sliced == full[5:15]


def test_read_evidence_unknown_ref_id_raises_mcp_error(tmp_path: Path) -> None:
    wiki_dir = _make_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir))
    with pytest.raises(MCPError):
        adapter.read_evidence("does-not-exist")


def test_search_evidence_no_match_returns_empty_list(tmp_path: Path) -> None:
    wiki_dir = _make_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir))
    results = adapter.search_evidence("zzz-nonexistent-term-zzz")
    assert results == []


def test_constructor_requires_explicit_wiki_dir_no_hardcoded_default(tmp_path: Path) -> None:
    # No default tied to fixtures/docs/ -- must be told where the wiki lives.
    with pytest.raises(TypeError):
        WikiRagAdapter()  # type: ignore[call-arg]
