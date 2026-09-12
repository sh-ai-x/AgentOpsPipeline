"""TDD regression - step 7 held-out experiment + manifest integrity."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentops_workbench.experiments.held_out import (
    ExperimentManifest,
    RunOutcome,
    SpendCeiling,
    _cost,
    _git_sha,
    write_manifest,
    write_outcomes,
)
from agentops_workbench.llm.adapter import Usage


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_spend_ceiling_defaults() -> None:
    c = SpendCeiling()
    assert c.max_usd == 5.0


def test_cost_function() -> None:
    c = SpendCeiling(max_usd=5.0, cost_per_1k_prompt_tokens=0.001, cost_per_1k_completion_tokens=0.002)
    usage = Usage(provider="p", model="m", prompt_tokens=1000, completion_tokens=500, total_tokens=1500, cost_usd=0.0)
    assert _cost(usage, c) == pytest.approx(0.002)


def test_git_sha_returns_string() -> None:
    sha = _git_sha(Path(__file__).resolve().parent.parent)
    assert isinstance(sha, str)


def test_write_and_read_manifest(tmp_path: Path) -> None:
    m = ExperimentManifest(
        started_at="2026-09-08T08:00:00+00:00",
        code_sha="abc1234",
        provider="minimax",
        model="MiniMax-M3[1m]",
        selected_topologies=["fixed", "single_agent"],
        held_out_sha256="d3bef8c35a3bf9de539ab67a988e83a2d5434746bc8c6001f85ddf569dc8d0a5",
        dataset_version="v1",
        prompt_version="v1_baseline",
        budget={"max_usd": 5.0},
    )
    p = tmp_path / "manifest.json"
    write_manifest(p, m)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["provider"] == "minimax"
    assert raw["selected_topologies"] == ["fixed", "single_agent"]


def test_write_outcomes_jsonl(tmp_path: Path) -> None:
    outcomes = [
        RunOutcome(
            run_id="r1", case_id="case-025", family_id="straightforward",
            topology="fixed", trial=0, task_success=True,
            retrieval_recall=1.0, tool_correctness=1.0,
            prompt_tokens=10, completion_tokens=20,
            cost_usd=0.05, duration_ms=120,
        ),
    ]
    p = tmp_path / "outcomes.jsonl"
    write_outcomes(p, outcomes)
    lines = [line for line in p.read_text(encoding="utf-8").split(chr(10)) if line]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["run_id"] == "r1"


def test_held_out_sha_uncontaminated(repo_root: Path) -> None:
    from agentops_workbench.benchmark.load import held_out_sha256
    expected = (repo_root / "fixtures" / "cases" / "HELD_OUT_SHA256.txt").read_text(encoding="utf-8").strip()
    actual = held_out_sha256(repo_root / "fixtures" / "cases")
    assert actual == expected


def test_held_out_split_has_six_cases(repo_root: Path) -> None:
    from agentops_workbench.benchmark.load import load_split
    held = load_split(repo_root / "fixtures" / "cases" / "held_out", "held_out")
    assert len(held) == 6


# ---- run_held_out.run() wiring — planner_executor inclusion + real
# tool_correctness scoring (both were silently missing before this fix) ----


def test_run_held_out_includes_all_three_topologies(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """selected_topologies must cover all three registered topologies --
    planner_executor was silently excluded before this fix, so its
    tool-execution path was never exercised by the held-out benchmark."""
    monkeypatch.setenv("AGENTOPS_PROVIDER", "local-fake")
    from agentops_workbench.experiments.run_held_out import run

    outcomes, manifest = run(repo_root, output_dir=tmp_path)
    assert set(manifest.selected_topologies) == {"fixed", "single_agent", "planner_executor"}
    assert {o.topology for o in outcomes} == {"fixed", "single_agent", "planner_executor"}
    assert len(outcomes) == 6 * 2 * 3  # 6 held-out cases x 2 trials x 3 topologies


def test_run_held_out_scores_tool_correctness_from_real_tool_results(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tool_correctness must reflect the run's actual tool_results, not an
    always-[] placeholder -- otherwise it stays 0.0 forever regardless of
    whether the graph really called a tool (the bug this regression pins:
    the scorer was never wired to run_topology()'s output at all)."""
    monkeypatch.setenv("AGENTOPS_PROVIDER", "local-fake")
    import agentops_workbench.experiments.run_held_out as mod

    def _fake_run_topology(name: str, adapter, task: str) -> dict:
        if name == "planner_executor":
            return {
                "answer": "ok",
                "tool_results": [
                    {"tool_name": "search_docs", "outcome": "ok", "latency_ms": 1,
                     "error_kind": None, "args": {}},
                    {"tool_name": "read_document", "outcome": "ok", "latency_ms": 1,
                     "error_kind": None, "args": {}},
                ],
            }
        return {"answer": "ok"}

    monkeypatch.setattr(mod, "run_topology", _fake_run_topology)
    outcomes, _ = mod.run(repo_root, output_dir=tmp_path)

    # case-025's allowed_tools are exactly [search_docs, read_document] --
    # both were "called" above, so every planner_executor call on it is
    # correct.
    case_025 = [o for o in outcomes if o.topology == "planner_executor" and o.case_id == "case-025"]
    assert case_025
    for o in case_025:
        assert o.tool_correctness == 1.0
    # fixed/single_agent never return tool_results here -- must stay 0.0,
    # unchanged (the .get(..., []) default preserves this).
    other = [o for o in outcomes if o.topology != "planner_executor"]
    assert other
    for o in other:
        assert o.tool_correctness == 0.0


def test_spend_ceiling_blocks_overrun() -> None:
    ceiling = SpendCeiling(max_usd=0.001)
    usage = Usage(provider="p", model="m", prompt_tokens=1000, completion_tokens=1000, total_tokens=2000, cost_usd=0.0)
    cost = _cost(usage, ceiling)
    total = 0.0
    projected = total + cost
    assert projected > ceiling.max_usd
