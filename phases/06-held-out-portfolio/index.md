# 06-held-out-portfolio

> Phase 6 — Held-out evaluation + evidence card + demo

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Phase 6"
- **Canonical step plan:** `.dev-kit/round-1/phases/build/step7.md` — local planning artefact, not tracked in git (`.dev-kit/round-1/` is `.gitignore`d). This page is the tracked, self-contained promotion of it.
- **Estimated:** 1.0 week (original plan value, not measured effort)
- **Exit criterion:** A reviewer can reproduce an offline failure and inspect the basis for the shipping decision
- **Status:** shipped — merged into `apps/agentops-workbench/` via PR #8
- **Build output:** [`step7-output.json`](step7-output.json) — reconstructed step record (see [`../build-report.md`](../build-report.md))

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
- Not done: the `experiment-v1-frozen` git tag was never cut; the demo is a script, not a recording

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
