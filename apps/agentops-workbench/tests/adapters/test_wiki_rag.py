"""WikiRagAdapter -- TF-IDF cosine similarity over a directory of .md files."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentops_workbench.adapters.base import EvidenceRef
from agentops_workbench.adapters.wiki_rag import (
    SKIP_DIR_NAMES,
    WikiRagAdapter,
    collect_wiki_files,
)
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


# ---- Generic-layout tests (recursive walk, junk skipping, collision handling) ----


def _make_nested_wiki(tmp_path: Path) -> Path:
    """Build a wiki with both flat and nested layouts, plus junk dirs.

    Tree:
        wiki/
          README.md                       # flat
          langgraph/
            checkpointing.md             # nested under category
            checkpointing.md             # duplicate stem in different dir → unique ref_id
            rate-limits.md
          fastapi/
            jwt-auth.md
            nested/
              deep-note.md
          .git/
            HEAD                          # ignored (junk dir)
            notes/
              leaked.md                   # must NOT be indexed
          .obsidian/
            config.json                   # not .md, ignored anyway
          node_modules/
            package/
              big.md                      # ignored
          _flat/
            from-oss-helper.md            # ignored (oss_helper artifact dir)
        subdir-collision/
          README.md                       # second README → must NOT collide
    """
    wiki_dir = tmp_path / "wiki"
    (wiki_dir / "langgraph").mkdir(parents=True)
    (wiki_dir / "langgraph" / "nested" / "fastapi").mkdir(parents=True)
    (wiki_dir / "fastapi" / "nested").mkdir(parents=True)
    (wiki_dir / ".git" / "notes").mkdir(parents=True)
    (wiki_dir / ".obsidian").mkdir(parents=True)
    (wiki_dir / "node_modules" / "package").mkdir(parents=True)
    (wiki_dir / "_flat").mkdir(parents=True)
    (tmp_path / "subdir-collision").mkdir(parents=True)

    (wiki_dir / "README.md").write_text(
        "Top-level README covers the workspace overview.", encoding="utf-8",
    )
    (wiki_dir / "langgraph" / "checkpointing.md").write_text(
        "LangGraph checkpointing persists state with PostgresCheckpointer.",
        encoding="utf-8",
    )
    (wiki_dir / "langgraph" / "nested" / "fastapi" / "checkpointing.md").write_text(
        "Second note with the same stem but in a deeper dir.",
        encoding="utf-8",
    )
    (wiki_dir / "langgraph" / "rate-limits.md").write_text(
        "Rate limits are enforced per principal.", encoding="utf-8",
    )
    (wiki_dir / "fastapi" / "jwt-auth.md").write_text(
        "JWT auth uses HS256 with a 48-byte secret.", encoding="utf-8",
    )
    (wiki_dir / "fastapi" / "nested" / "deep-note.md").write_text(
        "Deeply nested note that must still be indexed.", encoding="utf-8",
    )
    (wiki_dir / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (wiki_dir / ".git" / "notes" / "leaked.md").write_text(
        "Should NOT be indexed -- lives under .git.",
        encoding="utf-8",
    )
    (wiki_dir / ".obsidian" / "config.json").write_text("{}", encoding="utf-8")
    (wiki_dir / "node_modules" / "package" / "big.md").write_text(
        "Should NOT be indexed -- lives under node_modules.",
        encoding="utf-8",
    )
    (wiki_dir / "_flat" / "from-oss-helper.md").write_text(
        "Should NOT be indexed -- oss_helper _flat artifact.",
        encoding="utf-8",
    )
    (tmp_path / "subdir-collision" / "README.md").write_text(
        "Should NOT be indexed -- outside wiki_dir.",
        encoding="utf-8",
    )
    return wiki_dir


def test_collect_wiki_files_walks_subdirectories_recursively(tmp_path: Path) -> None:
    wiki_dir = _make_nested_wiki(tmp_path)
    files = collect_wiki_files(wiki_dir)

    # All legitimate .md under wiki_dir should be indexed.
    stems = {p.name for p in files.values()}
    assert "README.md" in stems
    assert "checkpointing.md" in stems
    assert "rate-limits.md" in stems
    assert "jwt-auth.md" in stems
    assert "deep-note.md" in stems
    # Junk-dir files must NOT appear.
    assert "leaked.md" not in stems
    assert "big.md" not in stems
    assert "from-oss-helper.md" not in stems
    # Outside-wiki_dir files must NOT appear.
    assert all(str(p).startswith(str(wiki_dir)) for p in files.values())


def test_collect_wiki_files_skips_known_junk_dirs(tmp_path: Path) -> None:
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    for junk in SKIP_DIR_NAMES:
        (wiki_dir / junk / "real-subdir").mkdir(parents=True)
        (wiki_dir / junk / "real-subdir" / "leak.md").write_text(
            "must not be indexed", encoding="utf-8",
        )
    (wiki_dir / "keep.md").write_text("must be indexed", encoding="utf-8")

    files = collect_wiki_files(wiki_dir)
    assert "keep" in files
    for ref_id, path in files.items():
        rel_parts = path.relative_to(wiki_dir).parts[:-1]  # dir components only
        for part in rel_parts:
            assert part not in SKIP_DIR_NAMES, (
                f"ref_id={ref_id} path={path} sits under skipped dir {part}"
            )


def test_flat_layout_keeps_stem_as_ref_id_for_backward_compat(tmp_path: Path) -> None:
    """The original tests (and oss-helper's flattened _flat layout) rely on
    `f.stem` being the ref_id when files sit directly under wiki_dir. Keep
    that contract; only encode the path for files nested in subdirs."""
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "checkpointing.md").write_text("PostgresCheckpointer notes.", encoding="utf-8")
    (wiki_dir / "rate-limits.md").write_text("429 notes.", encoding="utf-8")

    files = collect_wiki_files(wiki_dir)
    assert set(files) == {"checkpointing", "rate-limits"}


def test_nested_layout_encodes_path_into_ref_id(tmp_path: Path) -> None:
    wiki_dir = tmp_path / "wiki"
    (wiki_dir / "langgraph").mkdir(parents=True)
    (wiki_dir / "langgraph" / "checkpointing.md").write_text("x", encoding="utf-8")
    (wiki_dir / "fastapi").mkdir(parents=True)
    (wiki_dir / "fastapi" / "jwt-auth.md").write_text("y", encoding="utf-8")

    files = collect_wiki_files(wiki_dir)
    assert "langgraph__checkpointing" in files
    assert "fastapi__jwt-auth" in files
    # No collision: each ref_id points to a unique file.
    assert len(set(files.values())) == len(files)


def test_collision_in_same_dir_uses_counter_suffix(tmp_path: Path) -> None:
    """If `f.stem` collides inside the SAME dir (impossible on POSIX filenames
    but possible across dirs), the second occurrence gets a stable suffix."""
    wiki_dir = tmp_path / "wiki"
    (wiki_dir / "langgraph" / "nested" / "fastapi").mkdir(parents=True)
    (wiki_dir / "langgraph" / "checkpointing.md").write_text("first", encoding="utf-8")
    (wiki_dir / "langgraph" / "nested" / "fastapi" / "checkpointing.md").write_text(
        "second", encoding="utf-8",
    )

    files = collect_wiki_files(wiki_dir)
    # The two files must be reachable by distinct ref_ids.
    assert len(files) == 2
    assert all("checkpointing" in rid for rid in files)


def test_wiki_rag_adapter_searches_across_nested_dirs(tmp_path: Path) -> None:
    wiki_dir = _make_nested_wiki(tmp_path)
    adapter = WikiRagAdapter(wiki_dir=str(wiki_dir))

    # Query for a term that appears only in a deeply nested file.
    results = adapter.search_evidence("deep-note", top_k=5)
    assert results, "expected at least one hit for term living in nested dir"
    assert any("deep-note" in r.ref_id for r in results)

    # The .git-leaked file must NOT be retrievable through the adapter.
    leaked_ref_ids = [rid for rid in adapter._files if "leaked" in rid.lower()]
    assert not leaked_ref_ids, (
        f"leaked.md under .git/ leaked into the index: {leaked_ref_ids}"
    )


def test_collect_wiki_files_returns_empty_for_empty_or_missing_wiki_dir(tmp_path: Path) -> None:
    assert collect_wiki_files(tmp_path / "does-not-exist") == {}
    empty = tmp_path / "empty-wiki"
    empty.mkdir()
    assert collect_wiki_files(empty) == {}
