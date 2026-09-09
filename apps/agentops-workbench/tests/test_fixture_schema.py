"""Step 1.3 TDD regression — every pilot case must match schema and split=dev."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CASES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cases" / "pilot"
SCHEMA_PATH = CASES_DIR.parent / "schema.json"

REQUIRED_KEYS = {
    "id", "family_id", "task", "expected_outcome",
    "allowed_tools", "source_refs", "reviewer", "split",
}
ALLOWED_FAMILIES = {
    "straightforward", "multi_doc", "ambiguous",
    "missing_evidence", "stale_doc", "tool_failure",
}
ALLOWED_TOOLS = {
    "search_docs", "read_document", "get_issue",
    "create_ticket_draft", "publish_ticket",
}


def _load_case_ids() -> list[Path]:
    return sorted(CASES_DIR.glob("case-*.json"))


def test_pilot_directory_has_12_cases() -> None:
    ids = _load_case_ids()
    assert len(ids) == 30, f"expected 30 pilot cases (18 dev + 6 val + 6 held_out), found {len(ids)}"


@pytest.mark.parametrize("path", _load_case_ids())
def test_case_shape(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw.keys()) >= REQUIRED_KEYS
    assert re.match(r"^case-\d{3}$", raw["id"]), raw["id"]
    assert raw["family_id"] in ALLOWED_FAMILIES, raw["family_id"]
    assert raw["split"] in {"dev", "val", "held_out"},         f"unknown split {raw['split']!r}"
    assert raw["reviewer"], "reviewer must be set"
    assert isinstance(raw["allowed_tools"], list) and raw["allowed_tools"], \
        "allowed_tools must be a non-empty list"
    for t in raw["allowed_tools"]:
        assert t in ALLOWED_TOOLS, f"unknown tool {t!r}"


def test_schema_file_present() -> None:
    assert SCHEMA_PATH.exists(), f"missing {SCHEMA_PATH}"
    raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "properties" in raw and "required" in raw


def test_per_split_family_counts() -> None:
    """Each of the 6 families appears with the right count per split:
    dev: 3 per family (18), val: 1 per family (6), held_out: 1 per family (6).
    """
    by_split_fam: dict[str, dict[str, int]] = {"dev": {}, "val": {}, "held_out": {}}
    for p in _load_case_ids():
        raw = json.loads(p.read_text(encoding="utf-8"))
        s = raw["split"]
        f = raw["family_id"]
        by_split_fam[s][f] = by_split_fam[s].get(f, 0) + 1
    expected = {"dev": 3, "val": 1, "held_out": 1}
    for split, count in expected.items():
        assert set(by_split_fam[split].keys()) == ALLOWED_FAMILIES, (split, by_split_fam[split])
        for fam, n in by_split_fam[split].items():
            assert n == count, f"{split}/{fam} has {n} cases; expected {count}"
