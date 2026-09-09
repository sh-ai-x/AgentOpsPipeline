"""TDD regression - 3-prompt comparison harness."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentops_workbench.experiments.prompts import PromptRunOutcome


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def test_outcome_round_trip() -> None:
    o = PromptRunOutcome(
        run_id="x", case_id="c", family_id="f",
        prompt_version="v1_baseline", task_success=True,
        prompt_tokens=10, completion_tokens=20, cost_usd=0.0, duration_ms=100,
    )
    d = o.__dict__
    assert d["prompt_version"] == "v1_baseline"
    assert d["task_success"] is True


def test_prompt_files_exist(repo_root: Path) -> None:
    for name in ("v1_baseline.md", "v2_structured.md", "v3_minimal.md"):
        p = repo_root / "prompts" / name
        assert p.exists(), f"missing {p}"


def test_prompt_templates_have_task_placeholder(repo_root: Path) -> None:
    for name in ("v1_baseline.md", "v2_structured.md", "v3_minimal.md"):
        text = (repo_root / "prompts" / name).read_text()
        # v3_minimal intentionally has only {task}; others have more
        assert "{task}" in text, f"{name} missing {{task}} placeholder"
