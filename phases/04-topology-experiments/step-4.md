# Step 5 — Topology variants + planner/executor

**Phase:** 4 (proposal §"Phase 4: Topology and Planning Experiments")
**Branch:** `feat/04-topology-experiments`
**Worktree:** `.worktrees/04-topology-experiments`
**Methodology:** TDD
**Estimated:** 1.0 week

## Work items

### 5.1 Single-agent variant

- `src/agentops_workbench/graph/single_agent.py` — ReAct-style single agent bound to the same tool contracts as the fixed graph.

### 5.2 Bounded planner/executor variant

- `src/agentops_workbench/graph/planner_executor.py`:
  - `planner` proposes a 1–3 step plan from the task.
  - `executor` walks the plan with a per-step budget.
  - Stop conditions: plan complete, budget exhausted, escalation required.

### 5.3 Matched-budget comparison

- Same `model_config`, same `prompt_version` (winning one from Step 4), same corpus, same tool permissions, same step budget across all three topologies.
- 18 dev + 6 val cases × 3 topologies = 72 runs, single trial each.
- Track: task success, call count, p50/p95 latency, tokens, cost estimate.

### 5.4 Topology ADR

- `docs/adr/0006-topology.md` — recorded shipping choice + limitations.
- Explicit "staged selection" caveat: prompt and topology were not jointly optimized (a full factorial search is optional).

## TDD plan

1. **Red** `tests/test_single_agent.py` — single-agent reaches the same outcome as fixed graph on a golden input.
2. **Red** `tests/test_planner_executor.py` — bounded by step budget; refuses to escalate past cap.
3. **Red** `tests/test_topology_match.py` — same `prompt_version` + `model_config` + corpus across all three topologies (asserted from the run manifest, not asserted by re-running).

## Exit criteria

- 72 runs logged under `experiments/topology-v1/`.
- Topology ADR written and approved.
- One topology selected for the held-out experiment; rationale + limitations recorded.

## Risks

- Drift between topologies (R4): a test asserts manifest-level invariants (identical prompt/corpus/budget) without re-running the comparison.
- Planner over-spends: budget guard must be checked inside the executor, not just at planning time.
