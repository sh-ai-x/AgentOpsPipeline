"""ADR-0010 step 8: fixtures/wiki_eval/ gold set -- schema, split counts,
family coverage, and the held-out freeze."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentops_workbench.benchmark.wiki_eval_load import held_out_sha256, load_split

WIKI_EVAL_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "wiki_eval"
SCHEMA_PATH = WIKI_EVAL_DIR / "schema.json"

REQUIRED_KEYS = {
    "id", "family_id", "query", "relevant_refs",
    "partially_relevant_refs", "relevant_sections", "reviewer", "split",
}
ALLOWED_FAMILIES = {
    "single_hop", "multi_hop", "paraphrase", "synonym", "acronym", "no_answer",
}


def _all_query_files() -> list[Path]:
    return sorted(WIKI_EVAL_DIR.glob("queries/*/wq-*.json"))


def test_schema_file_present() -> None:
    assert SCHEMA_PATH.exists()
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "properties" in raw and "required" in raw


def test_corpus_directory_has_markdown_notes() -> None:
    notes = list(WIKI_EVAL_DIR.glob("corpus/**/*.md"))
    assert len(notes) >= 5


@pytest.mark.parametrize("path", _all_query_files())
def test_query_shape(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw.keys()) >= REQUIRED_KEYS
    assert raw["id"] == path.stem
    assert raw["family_id"] in ALLOWED_FAMILIES
    assert raw["split"] in {"dev", "val", "held_out"}
    assert raw["split"] == path.parent.name
    assert raw["reviewer"], "reviewer must be set"
    assert raw["query"].strip()


def test_every_relevant_ref_resolves_to_a_real_corpus_file() -> None:
    """A gold ref_id that doesn't exist in the corpus would silently make
    every mode fail that query -- catch it here, not during a comparison
    run. ref_id follows WikiRagAdapter's nested-path convention: dirs
    joined by "__", suffix stripped."""
    corpus_dir = WIKI_EVAL_DIR / "corpus"
    real_ref_ids = {
        "__".join(p.relative_to(corpus_dir).with_suffix("").parts)
        for p in corpus_dir.glob("**/*.md")
    }
    for path in _all_query_files():
        raw = json.loads(path.read_text(encoding="utf-8"))
        for ref in raw["relevant_refs"] + raw["partially_relevant_refs"]:
            assert ref in real_ref_ids, f"{path.name}: unknown ref_id {ref!r}"


def test_no_answer_family_has_empty_gold() -> None:
    for path in _all_query_files():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["family_id"] == "no_answer":
            assert raw["relevant_refs"] == []
            assert raw["partially_relevant_refs"] == []


def test_dev_split_covers_every_family() -> None:
    dev = load_split(WIKI_EVAL_DIR, "dev")
    assert {q.family_id for q in dev} == ALLOWED_FAMILIES


def test_all_query_ids_are_unique() -> None:
    ids = [json.loads(p.read_text(encoding="utf-8"))["id"] for p in _all_query_files()]
    assert len(ids) == len(set(ids))


def test_held_out_sha256_is_frozen() -> None:
    expected = (WIKI_EVAL_DIR / "HELD_OUT_SHA256.txt").read_text(encoding="utf-8").strip()
    actual = held_out_sha256(WIKI_EVAL_DIR)
    assert actual == expected, (
        "fixtures/wiki_eval/queries/held_out/ changed without refreezing "
        "HELD_OUT_SHA256.txt -- held-out data must not be tuned against."
    )
