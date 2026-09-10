# 04-topology-experiments

> Phase 4 — Topology variants + planner/executor

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Phase 4"
- **Canonical step plan:** `.dev-kit/round-1/phases/build/step5.md` — local planning artefact, not tracked in git (`.dev-kit/round-1/` is `.gitignore`d). This page is the tracked, self-contained promotion of it.
- **Estimated:** 1.0 week (original plan value, not measured effort)
- **Exit criterion:** Selection follows measured utility; a simpler workflow may win
- **Status:** shipped — merged into `apps/agentops-workbench/` via PR #8
- **Build output:** [`step5-output.json`](step5-output.json) — audit vs. acceptance criterion: **AC NOT met** (tool dispatch stubbed in both variants; comparison behind ADR-0006 is degenerate). See [`../build-report.md`](../build-report.md).

## Deliverables (planned)

- Single-agent (ReAct-style) variant on the same tool contracts
- Bounded planner/executor variant (1-3 step plan, per-step budget)
- Matched-budget comparison across all three topologies
- Topology ADR with the shipping choice + limitations

## What shipped

- `src/agentops_workbench/graph/{single_agent,planner_executor,topology}.py` behind one registry
- `docs/adr/0006-topology.md` — fixed graph shipped as the default
- Held-out run notes: `single_agent` burned 2-10x completion tokens vs `fixed` for no measured gain
- **Gap (see `step5-output.json`):** tool dispatch is `# stub for MVP` in *both* `single_agent` and `planner_executor`; `tool_correctness` is 0/24 on the held-out set, so the matched-budget comparison behind ADR-0006 is between three tool-less answer generators. `planner_executor` was not in the held-out run.

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
