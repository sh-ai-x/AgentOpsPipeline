"""Step 1.4 TDD regression — all 4 ADRs exist with required headings."""
from __future__ import annotations

from pathlib import Path

import pytest

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"

REQUIRED_ADRS = [
    "0001-langgraph.md",
    "0002-mcp-boundaries.md",
    "0003-provider-abstraction.md",
    "0004-dataset-separation.md",
    "0010-dense-retrieval-and-reranking.md",
    "0011-real-otel-export.md",
]


@pytest.mark.parametrize("filename", REQUIRED_ADRS)
def test_adr_exists(filename: str) -> None:
    p = ADR_DIR / filename
    assert p.exists(), f"missing ADR: {p}"


@pytest.mark.parametrize("filename", REQUIRED_ADRS)
def test_adr_has_decision_and_consequences(filename: str) -> None:
    p = ADR_DIR / filename
    text = p.read_text(encoding="utf-8")
    assert "## Decision" in text, f"{p} missing '## Decision' heading"
    assert "## Consequences" in text, f"{p} missing '## Consequences' heading"
