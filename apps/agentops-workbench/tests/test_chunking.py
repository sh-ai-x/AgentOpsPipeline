"""chunking.py -- markdown header-aware segmentation + recursive fallback.

ADR-0010 step 3. Pure stdlib, no ML. Setext headings (`===`/`---`
underlines) are explicitly out of scope -- an ATX-only chunker is a
documented boundary, not a stub.
"""
from __future__ import annotations

from agentops_workbench.chunking import (
    chunk_markdown,
    recursive_split,
    split_markdown_sections,
)


def test_empty_file_yields_no_sections_and_no_chunks() -> None:
    assert split_markdown_sections("") == []
    assert chunk_markdown("") == []


def test_no_headings_file_is_one_section_with_empty_heading_path() -> None:
    text = "Just a plain paragraph with no headings at all."
    sections = split_markdown_sections(text)
    assert len(sections) == 1
    assert sections[0].heading_path == ()
    assert sections[0].text == text


def test_single_top_level_heading_splits_preamble_from_section() -> None:
    text = "Intro line.\n\n# Title\n\nBody under title.\n"
    sections = split_markdown_sections(text)
    assert [s.heading_path for s in sections] == [(), ("Title",)]
    assert sections[0].text == "Intro line.\n\n"
    assert sections[1].text == "# Title\n\nBody under title.\n"


def test_nested_heading_path_tracks_the_full_ancestor_chain() -> None:
    text = (
        "# Persistence\n\n"
        "Overview.\n\n"
        "## Postgres checkpointer\n\n"
        "Uses Postgres.\n\n"
        "## Redis checkpointer\n\n"
        "Uses Redis.\n"
    )
    sections = split_markdown_sections(text)
    paths = [s.heading_path for s in sections]
    assert paths == [
        ("Persistence",),
        ("Persistence", "Postgres checkpointer"),
        ("Persistence", "Redis checkpointer"),
    ]


def test_heading_pops_back_to_the_correct_ancestor_level() -> None:
    text = (
        "# A\n\n"
        "## A1\n\ntext\n\n"
        "### A1a\n\ntext\n\n"
        "## A2\n\ntext\n\n"
        "# B\n\ntext\n"
    )
    sections = split_markdown_sections(text)
    paths = [s.heading_path for s in sections]
    assert paths == [
        ("A",),
        ("A", "A1"),
        ("A", "A1", "A1a"),
        ("A", "A2"),
        ("B",),
    ]


def test_headings_inside_a_fenced_code_block_are_not_treated_as_headings() -> None:
    text = (
        "# Real heading\n\n"
        "```bash\n"
        "# this is a shell comment, not a markdown heading\n"
        "echo hi\n"
        "```\n\n"
        "Trailing text.\n"
    )
    sections = split_markdown_sections(text)
    assert [s.heading_path for s in sections] == [("Real heading",)]
    assert "# this is a shell comment" in sections[0].text


def test_tilde_fences_are_also_respected() -> None:
    text = "# H\n\n~~~\n# not a heading\n~~~\n\nafter\n"
    sections = split_markdown_sections(text)
    assert [s.heading_path for s in sections] == [("H",)]


def test_frontmatter_is_kept_as_part_of_the_first_section() -> None:
    text = "---\ntags: [a, b]\n---\n\n# Title\n\nBody.\n"
    sections = split_markdown_sections(text)
    assert sections[0].heading_path == ()
    assert "tags: [a, b]" in sections[0].text
    assert sections[1].heading_path == ("Title",)


def test_frontmatter_only_file_is_a_single_section() -> None:
    text = "---\ntags: [a]\n---\n"
    sections = split_markdown_sections(text)
    assert len(sections) == 1
    assert sections[0].heading_path == ()


def test_section_offsets_round_trip_into_the_original_text() -> None:
    text = "Intro.\n\n# Title\n\nBody under title.\n\n## Sub\n\nMore.\n"
    for section in split_markdown_sections(text):
        assert text[section.start:section.end] == section.text


# ---- recursive_split ----


def test_recursive_split_returns_whole_text_when_under_the_limit() -> None:
    text = "short text"
    pieces = recursive_split(text, max_chars=1200, overlap=150)
    assert pieces == [(text, 0, len(text))]


def test_recursive_split_packs_paragraphs_up_to_the_limit() -> None:
    para = "word " * 20  # 100 chars
    text = "\n\n".join([para] * 5)  # ~520 chars incl separators
    pieces = recursive_split(text, max_chars=250, overlap=0)
    assert len(pieces) >= 2
    for piece_text, start, end in pieces:
        assert len(piece_text) <= 250 + 1  # allow the packed boundary itself
        assert text[start:end] == piece_text


def test_recursive_split_falls_back_to_sentences_for_an_oversized_paragraph() -> None:
    sentences = [f"This is sentence number {i} in a long paragraph." for i in range(20)]
    para = " ".join(sentences)  # one paragraph, no blank lines, too long for max_chars
    pieces = recursive_split(para, max_chars=120, overlap=0)
    assert len(pieces) >= 2
    for piece_text, start, end in pieces:
        assert para[start:end] == piece_text


def test_recursive_split_hard_slices_a_single_oversized_sentence() -> None:
    # One giant "sentence" (no period) that can't be split by paragraph or
    # sentence boundaries at all -- must fall back to a hard whitespace slice.
    words = ["word" + str(i) for i in range(200)]
    text = " ".join(words)  # a single unbroken "sentence", well over max_chars
    pieces = recursive_split(text, max_chars=100, overlap=0)
    assert len(pieces) >= 2
    for piece_text, start, end in pieces:
        assert len(piece_text) <= 100 + 1
        assert text[start:end] == piece_text
    # Round trip: every char of the original is covered exactly once in order.
    assert "".join(p[0] for p in pieces).replace(" ", "") in text.replace(" ", "")


def test_recursive_split_offsets_always_round_trip() -> None:
    text = ("Paragraph one is reasonably short.\n\n"
            + ("Paragraph two is much longer and repeats itself. " * 10)
            + "\n\nParagraph three.")
    pieces = recursive_split(text, max_chars=200, overlap=0)
    for piece_text, start, end in pieces:
        assert text[start:end] == piece_text


# ---- chunk_markdown ----


def test_chunk_markdown_single_chunk_for_a_short_section() -> None:
    text = "# Title\n\nShort body.\n"
    chunks = chunk_markdown(text, max_chars=1200, overlap=150)
    assert len(chunks) == 1
    assert chunks[0].heading_path == ("Title",)
    assert "Title" in chunks[0].text  # heading-prefixed embedding text
    assert "Short body." in chunks[0].text


def test_chunk_markdown_offsets_round_trip_for_every_chunk() -> None:
    text = (
        "# Title\n\n"
        + ("Body sentence. " * 100)
        + "\n\n## Sub\n\n"
        + ("More sentences here. " * 100)
    )
    chunks = chunk_markdown(text, max_chars=300, overlap=50)
    assert len(chunks) > 2
    for c in chunks:
        assert text[c.raw_start:c.raw_end] in c.text


def test_chunk_markdown_overlap_present_within_a_section() -> None:
    text = "# Title\n\n" + "".join(
        f"Sentence number {i} in a row. " for i in range(41)
    )
    chunks = chunk_markdown(text, max_chars=150, overlap=50)
    assert len(chunks) >= 2
    # Consecutive chunks under the same heading share overlapping raw spans.
    same_heading = [c for c in chunks if c.heading_path == ("Title",)]
    assert any(
        same_heading[i].raw_start < same_heading[i - 1].raw_end
        for i in range(1, len(same_heading))
    )


def test_chunk_markdown_overlap_does_not_cross_a_section_boundary() -> None:
    text = (
        "# A\n\n" + ("Filler sentence for section A. " * 40) + "\n\n"
        "# B\n\n" + ("Filler sentence for section B. " * 40)
    )
    chunks = chunk_markdown(text, max_chars=200, overlap=80)
    a_chunks = [c for c in chunks if c.heading_path == ("A",)]
    b_chunks = [c for c in chunks if c.heading_path == ("B",)]
    assert a_chunks and b_chunks
    # The first B chunk must not reach back into A's raw span.
    a_end = max(c.raw_end for c in a_chunks)
    assert b_chunks[0].raw_start >= a_end


def test_chunk_markdown_empty_file_returns_no_chunks() -> None:
    assert chunk_markdown("") == []
