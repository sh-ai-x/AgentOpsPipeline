"""Markdown chunking for non-lexical retrieval modes (ADR-0010 §2/§3).

Two-stage algorithm, both pure stdlib, no ML:

1. `split_markdown_sections` -- ATX heading-aware segmentation (`#`..`######`).
   Headings inside fenced code blocks (``` or ~~~) are not treated as
   headings. YAML frontmatter (`---`...`---` at the top of the file) is
   folded into the first section. Setext headings (`===`/`---` underlines)
   are deliberately NOT supported -- an explicit, documented boundary, not a
   stub: they are ambiguous with a `---` frontmatter delimiter and with a
   Markdown thematic break, and ATX headings are what every fixture note in
   this project's wiki actually uses.
2. `recursive_split` -- for any section over `max_chars`, pack paragraphs
   (blank-line separated) up to the limit; a paragraph that alone exceeds
   the limit is split into sentences (`text_utils.split_sentences`) and
   packed the same way; a single sentence still over the limit is hard-sliced
   on whitespace. `overlap` chars of the previous chunk's tail are folded
   into the next chunk within the same section (never across sections).

`chunk_markdown` composes both stages into `ChunkSpec`s carrying both the
heading-prefixed text used for embedding (heading context measurably helps
dense retrieval and costs nothing) and the raw `(start, end)` offsets into
the *original* document -- callers must be able to recover the literal
substring a chunk came from, so citations quote what is actually in the file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text_utils import split_sentences

_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_TOKEN_RE = re.compile(r"^(`{3,}|~{3,})")
_PARA_SPLIT_RE = re.compile(r"\n{2,}")

_CHUNK_MAX_CHARS = 1200
_CHUNK_OVERLAP_CHARS = 150


@dataclass(frozen=True)
class Section:
    """One heading-delimited span of a markdown document."""

    heading_path: tuple[str, ...]
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class ChunkSpec:
    """One retrieval-ready chunk: embedding text + a raw span in the source."""

    heading_path: tuple[str, ...]
    text: str
    raw_start: int
    raw_end: int


def split_markdown_sections(text: str) -> list[Section]:
    """Split `text` into heading-delimited sections, respecting fences.

    Content before the first heading (including any YAML frontmatter) forms
    a leading section with `heading_path == ()`; it is dropped only when
    genuinely empty (the file starts with a heading at line 0).
    """
    if not text:
        return []
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    total_len = pos

    start_idx = 0
    if lines and lines[0].rstrip("\n") == "---":
        j = 1
        while j < len(lines) and lines[j].rstrip("\n") != "---":
            j += 1
        if j < len(lines):
            start_idx = j + 1  # consume the closing '---' line too

    heading_stack: list[tuple[int, str]] = []
    boundaries: list[tuple[int, tuple[str, ...]]] = [(0, ())]
    in_fence = False
    fence_char = ""
    for i in range(start_idx, len(lines)):
        line = lines[i]
        stripped = line.strip()
        fence_m = _FENCE_TOKEN_RE.match(stripped)
        if fence_m:
            ch = fence_m.group(1)[0]
            if not in_fence:
                in_fence = True
                fence_char = ch
            elif ch == fence_char:
                in_fence = False
            continue
        if in_fence:
            continue
        heading_m = _ATX_HEADING_RE.match(line.rstrip("\n"))
        if heading_m:
            level = len(heading_m.group(1))
            title = heading_m.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            boundaries.append((i, tuple(t for _, t in heading_stack)))

    sections: list[Section] = []
    for b_i, (line_idx, heading_path) in enumerate(boundaries):
        start_char = offsets[line_idx]
        end_line_idx = boundaries[b_i + 1][0] if b_i + 1 < len(boundaries) else len(lines)
        end_char = offsets[end_line_idx] if end_line_idx < len(offsets) else total_len
        raw = text[start_char:end_char]
        if not raw:
            continue
        sections.append(Section(heading_path=heading_path, text=raw, start=start_char, end=end_char))
    return sections


def recursive_split(
    text: str, *, max_chars: int, overlap: int
) -> list[tuple[str, int, int]]:
    """Paragraph -> sentence -> hard-slice packing of `text` to `max_chars`.

    Returns `(piece_text, start, end)` triples with offsets relative to
    `text` itself (the caller shifts them when `text` is a section
    substring of a larger document). Every returned triple satisfies
    `text[start:end] == piece_text` by construction.
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [(text, 0, len(text))]

    paras: list[tuple[str, int, int]] = []
    last = 0
    for m in _PARA_SPLIT_RE.finditer(text):
        paras.append((text[last:m.start()], last, m.start()))
        last = m.end()
    paras.append((text[last:], last, len(text)))
    paras = [p for p in paras if p[0].strip() != ""]
    if not paras:
        paras = [(text, 0, len(text))]

    chunks: list[tuple[str, int, int]] = []
    cur_start: int | None = None
    cur_end: int | None = None

    def flush() -> None:
        nonlocal cur_start, cur_end
        if cur_start is not None:
            chunks.append((text[cur_start:cur_end], cur_start, cur_end))
            cur_start, cur_end = None, None

    for para_text, p_start, p_end in paras:
        if len(para_text) <= max_chars:
            if cur_start is None:
                cur_start, cur_end = p_start, p_end
            elif p_end - cur_start <= max_chars:
                cur_end = p_end
            else:
                flush()
                cur_start, cur_end = p_start, p_end
            continue

        # Paragraph itself is oversized -- flush whatever was packed, then
        # fall back to sentence-level packing within this paragraph.
        flush()
        sentences = split_sentences(para_text) or [para_text]
        s_scan = 0
        sent_start: int | None = None
        sent_end: int | None = None
        for sent in sentences:
            idx = para_text.find(sent, s_scan)
            if idx < 0:
                idx = s_scan
            abs_start = p_start + idx
            abs_end = abs_start + len(sent)
            s_scan = idx + len(sent)

            if len(sent) > max_chars:
                if sent_start is not None:
                    chunks.append((text[sent_start:sent_end], sent_start, sent_end))
                    sent_start = None
                slice_pos = abs_start
                while slice_pos < abs_end:
                    cut = min(slice_pos + max_chars, abs_end)
                    if cut < abs_end:
                        ws = text.rfind(" ", slice_pos, cut)
                        if ws > slice_pos:
                            cut = ws
                    chunks.append((text[slice_pos:cut], slice_pos, cut))
                    slice_pos = cut
                continue

            if sent_start is None:
                sent_start, sent_end = abs_start, abs_end
            elif abs_end - sent_start <= max_chars:
                sent_end = abs_end
            else:
                chunks.append((text[sent_start:sent_end], sent_start, sent_end))
                sent_start, sent_end = abs_start, abs_end
        if sent_start is not None:
            chunks.append((text[sent_start:sent_end], sent_start, sent_end))

    flush()

    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_start, prev_end = chunks[i - 1][1], chunks[i - 1][2]
            _, cur_s, cur_e = chunks[i]
            ov_start = max(prev_end - overlap, prev_start, 0)
            ov_start = min(ov_start, cur_s)
            overlapped.append((text[ov_start:cur_e], ov_start, cur_e))
        chunks = overlapped

    return [c for c in chunks if c[0].strip() != ""]


def chunk_markdown(
    text: str,
    *,
    max_chars: int = _CHUNK_MAX_CHARS,
    overlap: int = _CHUNK_OVERLAP_CHARS,
) -> list[ChunkSpec]:
    """Chunk a markdown document: header-aware sections, recursive fallback."""
    out: list[ChunkSpec] = []
    for section in split_markdown_sections(text):
        if len(section.text) <= max_chars:
            pieces = [(section.text, section.start, section.end)]
        else:
            raw_pieces = recursive_split(section.text, max_chars=max_chars, overlap=overlap)
            pieces = [(t, section.start + s, section.start + e) for (t, s, e) in raw_pieces]

        heading_prefix = " > ".join(section.heading_path)
        for raw, raw_start, raw_end in pieces:
            if not raw.strip():
                continue
            embed_text = f"{heading_prefix}\n\n{raw}" if heading_prefix else raw
            out.append(
                ChunkSpec(
                    heading_path=section.heading_path,
                    text=embed_text,
                    raw_start=raw_start,
                    raw_end=raw_end,
                )
            )
    return out
