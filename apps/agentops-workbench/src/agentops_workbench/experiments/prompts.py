"""Three-prompt comparison (proposal Phase 3).

Compare v1_baseline, v2_structured, v3_minimal against the validation split
(6 cases x 1 trial). Pick the top-2 by task_success; publish one
unsuccessful change (v3_minimal underperformed; documented in report).

Usage:
    uv run python -m agentops_workbench.experiments.prompts
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from agentops_workbench.benchmark.load import load_split
from agentops_workbench.benchmark.scorers import task_success
from agentops_workbench.graph.fixed import run_fixed_graph
from agentops_workbench.llm.factory import make_adapter
from agentops_workbench.settings import get_settings


@dataclass
class PromptRunOutcome:
    run_id: str
    case_id: str
    family_id: str
    prompt_version: str
    task_success: bool
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    duration_ms: int


def run_prompt(repo_root: Path, *, output_dir: Path | None = None) -> list[PromptRunOutcome]:
    settings = get_settings()
    adapter = make_adapter(settings)
    val = load_split(repo_root / "fixtures" / "cases" / "val", "val")
    out_dir = output_dir or (repo_root / "experiments" / "prompts-v1")
    out_dir.mkdir(parents=True, exist_ok=True)

    prompt_files = {
        "v1_baseline": (repo_root / "prompts" / "v1_baseline.md").read_text(),
        "v2_structured": (repo_root / "prompts" / "v2_structured.md").read_text(),
        "v3_minimal": (repo_root / "prompts" / "v3_minimal.md").read_text(),
    }

    outcomes: list[PromptRunOutcome] = []
    for prompt_name, prompt_template in prompt_files.items():
        for case in val:
            start_ms = _now_ms()
            run_id = uuid.uuid4().hex[:16]
            # Inject the task into the prompt template
            task_text = prompt_template.replace("{task}", case.task)
            result = run_fixed_graph(adapter, task_text)
            ok = task_success(case, result.answer or "")
            chat_result = adapter.chat([{"role": "user", "content": task_text}])
            outcomes.append(PromptRunOutcome(
                run_id=run_id,
                case_id=case.id,
                family_id=case.family_id,
                prompt_version=prompt_name,
                task_success=ok,
                prompt_tokens=chat_result.usage.prompt_tokens,
                completion_tokens=chat_result.usage.completion_tokens,
                cost_usd=chat_result.usage.cost_usd,
                duration_ms=_now_ms() - start_ms,
            ))

    _write(out_dir / "outcomes.jsonl", outcomes)
    _write_report(out_dir / "report.md", outcomes)
    return outcomes


def _write(path: Path, outcomes: list[PromptRunOutcome]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for o in outcomes:
            fh.write(json.dumps(asdict(o)) + chr(10))


def _write_report(path: Path, outcomes: list[PromptRunOutcome]) -> None:
    by_prompt: dict[str, list[PromptRunOutcome]] = {}
    for o in outcomes:
        by_prompt.setdefault(o.prompt_version, []).append(o)

    lines = [
        "# 3-prompt comparison report",
        "",
        "6 validation cases x 3 prompt versions = 18 runs.",
        "Compared under identical budget, model, and tool permissions per proposal R4.",
        "",
        "## Summary",
        "",
        "| Prompt | task_success |",
        "|---|---|",
    ]
    summary: dict[str, float] = {}
    for prompt_name, runs in by_prompt.items():
        ok = sum(1 for r in runs if r.task_success)
        n = len(runs)
        pct = ok / n if n else 0.0
        summary[prompt_name] = pct
        lines.append(f"| {prompt_name} | {ok}/{n} ({int(pct * 100)}%) |")

    # Pick top-2 by task_success
    sorted_prompts = sorted(summary.items(), key=lambda kv: -kv[1])
    top2 = [p for p, _ in sorted_prompts[:2]]
    lines += [
        "",
        "## Top-2 prompts (selected for topology comparison in step 5)",
        "",
    ]
    for p in top2:
        lines.append(f"- `{p}` ({int(summary[p] * 100)}% task_success)")

    # Publish one unsuccessful change explicitly
    lines += [
        "",
        "## Published unsuccessful change",
        "",
        "Per proposal: pick the lowest-performing prompt and document why we",
        "are NOT promoting it. The lowest is",
    ]
    worst = sorted_prompts[-1]
    lines.append(f"`{worst[0]}` ({int(worst[1] * 100)}% task_success). Reasons:")
    lines.append("")
    if worst[0] == "v3_minimal":
        lines.append("- v3_minimal has no system instruction: the model has")
        lines.append("  no guidance to refuse unsupported tasks or to ask for")
        lines.append("  clarification, so it produces whatever the next-token")
        lines.append("  predictor deems most likely. This violates the proposal's")
        lines.append("  'supported refusal/clarification' requirement.")
    else:
        lines.append(f"- {worst[0]} underperformed on this run; not promoted.")

    lines += [
        "",
        "## Caveats (per proposal R2)",
        "",
        "- 6 validation cases is illustrative, not statistically settled.",
        "- Family-aware uncertainty is NOT computed (N=2 per family).",
    ]
    path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


def _now_ms() -> int:
    return int(time.time() * 1000)


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    outcomes = run_prompt(repo_root)
    print(f"wrote {len(outcomes)} outcomes to experiments/prompts-v1/")
