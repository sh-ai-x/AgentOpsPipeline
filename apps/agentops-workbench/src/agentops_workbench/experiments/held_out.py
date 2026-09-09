"""Held-out experiment data types."""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentops_workbench.llm.adapter import Usage


@dataclass
class SpendCeiling:
    max_usd: float = 5.00
    cost_per_1k_prompt_tokens: float = 0.001
    cost_per_1k_completion_tokens: float = 0.002


@dataclass
class RunOutcome:
    run_id: str
    case_id: str
    family_id: str
    topology: str
    trial: int
    task_success: bool
    retrieval_recall: float
    tool_correctness: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    duration_ms: int
    error: str | None = None


@dataclass
class ExperimentManifest:
    started_at: str
    code_sha: str
    provider: str
    model: str
    selected_topologies: list[str]
    held_out_sha256: str
    dataset_version: str
    prompt_version: str
    budget: dict[str, Any] = field(default_factory=dict)


def _git_sha(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _cost(usage: Usage, ceiling: SpendCeiling) -> float:
    return (
        usage.prompt_tokens / 1000 * ceiling.cost_per_1k_prompt_tokens
        + usage.completion_tokens / 1000 * ceiling.cost_per_1k_completion_tokens
    )


def write_manifest(path: Path, manifest: ExperimentManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True) + chr(10), encoding="utf-8")


def write_outcomes(path: Path, outcomes: list[RunOutcome]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for o in outcomes:
            fh.write(json.dumps(asdict(o)) + chr(10))
