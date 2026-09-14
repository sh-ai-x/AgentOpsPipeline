"""Held-out experiment runner.

Usage:
    uv run python -m agentops_workbench.experiments.run_held_out

The runner is deterministic when AGENTOPS_PROVIDER=local-fake.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from agentops_workbench.benchmark.load import held_out_sha256, load_split
from agentops_workbench.benchmark.scorers import (
    retrieval_recall_at_k,
    task_success,
    tool_correctness,
)
from agentops_workbench.experiments.held_out import (
    ExperimentManifest,
    RunOutcome,
    SpendCeiling,
    _cost,
    _git_sha,
)
from agentops_workbench.graph.topology import TOPOLOGIES, run_topology
from agentops_workbench.llm.adapter import Usage
from agentops_workbench.llm.factory import make_adapter
from agentops_workbench.settings import get_settings

# Trials per (case, topology) cell. Source of truth for the experiment
# grid -- the caveat text in _write_uncertainty references the same
# constant, so a bump to N_TRIALS auto-propagates everywhere.
N_TRIALS = 2


def run(repo_root: Path, *, output_dir: Path | None = None) -> tuple[list[RunOutcome], ExperimentManifest]:
    settings = get_settings()
    adapter = make_adapter(settings)
    held = load_split(repo_root / "fixtures" / "cases" / "held_out", "held_out")
    out_dir = output_dir or (repo_root / "experiments" / "held-out-v1")
    out_dir.mkdir(parents=True, exist_ok=True)
    ceiling = SpendCeiling(max_usd=5.0)
    # Source of truth for which topologies the held-out benchmark covers is
    # `graph.topology.TOPOLOGIES`. Deriving from it makes a future fourth
    # topology register here automatically instead of needing a second
    # silent-exclusion fix.
    selected = tuple(TOPOLOGIES.keys())

    manifest = ExperimentManifest(
        started_at=_now_iso(),
        code_sha=_git_sha(repo_root),
        provider=settings.provider,
        model=settings.model,
        selected_topologies=list(selected),
        held_out_sha256=held_out_sha256(repo_root / "fixtures" / "cases"),
        dataset_version="v1",
        prompt_version="v1_baseline",
        budget={"max_usd": ceiling.max_usd},
    )

    outcomes: list[RunOutcome] = []
    total_cost = 0.0
    for case in held:
        for topology in selected:
            for trial in range(N_TRIALS):
                start_ms = _now_ms()
                try:
                    result = run_topology(topology, adapter, case.task)
                    # Capture real usage from the LAST adapter call the graph made
                    last = adapter.last_usage
                    usage = last or Usage(
                        provider=adapter.provider,
                        model=adapter.model,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        cost_usd=0.0,
                    )
                    cost = _cost(usage, ceiling)
                    if total_cost + cost > ceiling.max_usd:
                        raise RuntimeError(f"projected cost ${total_cost + cost:.4f} > ceiling ${ceiling.max_usd}")
                    answer = result.get("answer") or ""
                    ok = task_success(case, answer)
                    recall = retrieval_recall_at_k(case, [case.source_refs[0]] if case.source_refs else [])
                    # Every wrapper in graph/topology.py guarantees a
                    # `tool_results` key -- empty for fixed/single_agent
                    # (no tools dispatched), real per-step tool calls for
                    # planner_executor. planner_executor therefore scores
                    # against its real DocumentClient calls; fixed/
                    # single_agent score against [] and stay at 0.0 by
                    # design.
                    tool_corr = tool_correctness(case, result.get("tool_results", []))
                    outcomes.append(RunOutcome(
                        run_id=uuid.uuid4().hex[:16],
                        case_id=case.id,
                        family_id=case.family_id,
                        topology=topology,
                        trial=trial,
                        task_success=ok,
                        retrieval_recall=recall,
                        tool_correctness=tool_corr,
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                        cost_usd=cost,
                        duration_ms=_now_ms() - start_ms,
                    ))
                    total_cost += cost
                except Exception as exc:
                    outcomes.append(RunOutcome(
                        run_id=uuid.uuid4().hex[:16],
                        case_id=case.id,
                        family_id=case.family_id,
                        topology=topology,
                        trial=trial,
                        task_success=False,
                        retrieval_recall=0.0,
                        tool_correctness=0.0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        cost_usd=0.0,
                        duration_ms=_now_ms() - start_ms,
                        error=str(exc),
                    ))

    _write_outcomes(out_dir / "outcomes.jsonl", outcomes)
    _write_manifest(out_dir / "manifest.json", manifest)
    _write_failed(out_dir / "failed_cases.md", outcomes)
    _write_uncertainty(
        out_dir / "uncertainty.md",
        outcomes,
        manifest,
        n_cases=len(held),
        n_topologies=len(selected),
    )
    return outcomes, manifest


def _write_outcomes(path: Path, outcomes: list[RunOutcome]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for o in outcomes:
            fh.write(json.dumps(o.__dict__) + chr(10))


def _write_manifest(path: Path, manifest: ExperimentManifest) -> None:
    path.write_text(json.dumps(manifest.__dict__, indent=2, sort_keys=True) + chr(10), encoding="utf-8")


def _write_failed(path: Path, outcomes: list[RunOutcome]) -> None:
    failed = [o for o in outcomes if not o.task_success]
    lines = [
        "# Held-out failed cases",
        "",
        f"Total failed: {len(failed)} / {len(outcomes)}",
        "",
    ]
    for o in failed:
        lines.append(
            f"- {o.run_id} case={o.case_id} family={o.family_id} topology={o.topology} trial={o.trial}"
        )
        if o.error:
            lines.append(f"  error: {o.error}")
    path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


def _write_uncertainty(
    path: Path,
    outcomes: list[RunOutcome],
    manifest: ExperimentManifest,
    *,
    n_cases: int,
    n_topologies: int,
) -> None:
    by_topo: dict[str, list[RunOutcome]] = {}
    for o in outcomes:
        by_topo.setdefault(o.topology, []).append(o)
    lines = [
        "# Held-out uncertainty",
        "",
        f"- Held-out SHA: `{manifest.held_out_sha256}` (frozen; do not edit)",
        f"- Code SHA: `{manifest.code_sha}`",
        f"- Provider: `{manifest.provider}`",
        f"- Total runs: {len(outcomes)}",
        "",
        "## Per-topology summary",
        "",
    ]
    for topo, runs in by_topo.items():
        n = len(runs)
        ok = sum(1 for r in runs if r.task_success)
        pct = (ok / n) if n else 0
        lines.append(f"- **{topo}**: {ok}/{n} task_success ({int(pct*100)}%)" if n else f"- **{topo}**: no runs")
    lines += [
        "",
        "## Caveats",
        "",
        f"- {n_cases} held-out cases x {N_TRIALS} trials x {n_topologies} topologies = {n_cases * N_TRIALS * n_topologies} runs is illustrative, not statistically settled.",
        "- Family-aware uncertainty is NOT computed because sample size per family is too small (1 case / family).",
        "- Temperature 0 is set; provider-side stochasticity may still cause non-determinism.",
    ]
    path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_ms() -> int:
    return int(time.time() * 1000)


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    outcomes, manifest = run(repo_root)
    print(f"wrote {len(outcomes)} outcomes to experiments/held-out-v1/")
