# 06-held-out-portfolio

> Phase 6 — Held-out evaluation + evidence card + demo

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Phase 6"
- **Canonical step plan:** `.dev-kit/round-1/phases/build/step7.md` — local planning artefact, not tracked in git (`.dev-kit/round-1/` is `.gitignore`d). This page is the tracked, self-contained promotion of it.
- **Estimated:** 1.0 week (original plan value, not measured effort)
- **Exit criterion:** A reviewer can reproduce an offline failure and inspect the basis for the shipping decision
- **Status:** shipped — merged into `apps/agentops-workbench/` via PR #8
- **Build output:** [`step7-output.json`](step7-output.json) — audit vs. acceptance criterion: **AC partial** (reproducible, but task_success/tool_correctness 0/24; freeze tag + demo recording missing). See [`../build-report.md`](../build-report.md).

## Deliverables (planned)

- Frozen configs (planned git tag `experiment-v1-frozen`)
- 24-run held-out experiment (6 cases x 2 topologies x 2 trials)
- Raw outcomes + dependency manifest + failed cases
- 5-minute demo recording; evidence card

## What shipped

- `experiments/held-out-v1/{outcomes.jsonl,manifest.json,failed_cases.md,uncertainty.md}`
- Live run: `provider=minimax`, `MiniMax-M3`, 24 runs, 9,074 tokens, $0.0124, 153.7s
- Held-out SHA256 `d3bef8c3...d8d0a5`; code SHA `a5b489b`; `prompt_version=v1_baseline`
- `docs/EVIDENCE_CARD.md`, `docs/demo.md` (5-minute demo script)
- **Gaps (see `step7-output.json`):** `task_success` 0/24 and `tool_correctness` 0/24 — the shipping basis is `retrieval_recall` + token count, not an end-to-end signal (a consequence of the stubbed tools in steps 5–6); the `experiment-v1-frozen` tag was never cut; the demo is a script, not a recording

**Post-launch patches**: none since PR #8. Held-out re-run on the post-PR-#8 code is **not yet performed** — the live measurements (`24 runs, 9,074 tokens, $0.0124`) are still from PR #8's run. A re-run on the new retrieval-normalization + synthesis code would update numbers; not done in this scope.

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
