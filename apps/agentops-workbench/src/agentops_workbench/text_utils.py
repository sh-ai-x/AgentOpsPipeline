"""Tokenization / sentence-splitting / citation-extraction primitives.

Extracted from `wiki_corpus.py` (pure move, no behaviour change) so
`chunking.py` can depend on the sentence splitter without importing
`wiki_corpus`, which itself imports `adapters.wiki_rag` — importing
`wiki_corpus` from `chunking` (which `wiki_rag` will import for
non-lexical retrieval modes, ADR-0010) would otherwise close a
`wiki_rag -> chunking -> wiki_corpus -> wiki_rag` cycle.

`wiki_corpus.py` re-exports every name below so existing callers
(`groundedness.py`, `tests/test_wiki_corpus.py`) are unaffected.
"""
from __future__ import annotations

import re

# Mirror WikiRagAdapter's _TOKEN_RE = re.compile(r"[a-z0-9]+") so search-side
# tokenization produces the same tokens that built the TF-IDF index.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Sentence splitter. Avoids splitting on common abbreviations and
# decimal points so we don't over-segment. Each lookbehind is a
# fixed-width string so re.compile accepts the pattern (Python's re
# doesn't allow variable-width lookbehinds).
#
# A new sentence starts after `. ` when the next non-space char is
# uppercase, a quote, OR a `[` — that last case matters because LLMs
# commonly emit "...checkpoint. [ref-x] MongoDB is unrelated." and we
# need to split there. We post-process below to attach a leading
# `[ref-x]` to the previous sentence's citation slot, so the
# citation follows (not leads) the sentence it grounds.
_SENT_SPLIT_RE = re.compile(
    r"(?<!\bMr)(?<!\bDr)(?<!\bMrs)(?<!\bMs)(?<!\bSt)(?<!\bvs)(?<!\betc)"
    r"(?<!\be\.g)(?<!\bi\.e)"
    r"\.\s+(?=[A-Z\"'\[])"
)

# Citation regex: bracketed tokens, allowing ``__`` and ``.`` for path-
# encoded ref_ids like ``guides__install``. Trailing punctuation is
# tolerated but stripped.
_CITATION_RE = re.compile(r"\[([A-Za-z0-9_.~-]+)\]")

# Matches a leading citation `[ref-x]` (with optional whitespace) at the
# start of a sentence; used by `split_sentences` to reattach such
# citations to the previous sentence.
_LEADING_CITATION_RE = re.compile(r"\s*\[([A-Za-z0-9_.~-]+)\]")


def tokenize(text: str) -> list[str]:
    """Lower-case alphanumeric tokens, mirroring WikiRagAdapter."""
    return _TOKEN_RE.findall(text.lower())


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences.

    Handles common abbreviations and decimal points so we don't split
    inside them. Empty/whitespace-only input returns [].

    Post-processing: a leading `[ref-x]` citation on a sentence is
    moved to the end of the previous sentence. LLMs emit
    "...checkpoint. [ref-x] MongoDB is unrelated." — we want
    `checkpoint.` to be its own sentence (so its citation follows it),
    not have `[ref-x]` lead the next sentence (which would attribute
    the wrong claim).
    """
    text = text.strip()
    if not text:
        return []
    raw = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]
    if len(raw) <= 1:
        return raw
    out: list[str] = []
    for i, sent in enumerate(raw):
        m = _LEADING_CITATION_RE.match(sent)
        if m and i > 0:
            # Attach the leading citation to the previous sentence.
            out[-1] = f"{out[-1]} {m.group(0).strip()}"
            out.append(sent[m.end():].strip())
        else:
            out.append(sent)
    # Drop any empty trailing entries produced by the move.
    return [s for s in out if s]


def extract_citation_refs(text: str) -> list[str]:
    """Extract unique `[ref_id]` citations, preserving first-occurrence order."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _CITATION_RE.finditer(text):
        rid = m.group(1)
        # Strip a trailing period that's likely punctuation, not part of
        # the ref_id. (e.g. `[ref-a].` -> `ref-a`)
        if rid.endswith(".") and not rid.endswith(".."):
            rid = rid[:-1]
        if rid and rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out
