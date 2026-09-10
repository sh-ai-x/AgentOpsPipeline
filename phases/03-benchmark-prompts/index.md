# 03-benchmark-prompts

> Phase 3 — 30-case dataset + scorers + prompt experiments

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Phase 3"
- **Canonical step plan:** `.dev-kit/round-1/phases/build/step4.md` — local planning artefact, not tracked in git (`.dev-kit/round-1/` is `.gitignore`d). This page is the tracked, self-contained promotion of it.
- **Estimated:** 1.0 week (original plan value, not measured effort)
- **Exit criterion:** Every promoted case is traceable and held-out data has not influenced tuning
- **Status:** shipped — merged into `apps/agentops-workbench/` via PR #8
- **Build output:** [`step4-output.json`](step4-output.json) — audit vs. acceptance criterion: **AC met** (frozen held-out SHA + per-case reviewer + tuning on val only). See [`../build-report.md`](../build-report.md).

## Deliverables (planned)

- 30 cases across 6 families; frozen 18 dev / 6 val / 6 held-out split
- Held-out set content-hashed into `fixtures/cases/HELD_OUT_SHA256.txt`
- Node + task scorers
- 3-prompt comparison on validation; one published unsuccessful change

## What shipped

- `fixtures/cases/{dev,val,held_out}/case-*.json`, `HELD_OUT_SHA256.txt`
- `src/agentops_workbench/benchmark/{scorers,load}.py`
- `experiments/prompts-v1/{report.md,outcomes.jsonl}` — 18 live runs on `MiniMax-M3`
- `v3_minimal` published as the unsuccessful change (no system prompt -> longer, less-focused output)

**Post-launch patches** (since PR #8):
- PR #14: when running under `provider=local-fake`, the benchmark output now uses `LocalFakeAdapter.chat()` synthesis (quoted passages + 'see also' from the corpus) instead of round-robin canned lines. Held-out numbers from PR #8 are unchanged — synthesis affects presentation, not retrieval outcomes.
- PR #10: retrieval normalization (tokenization, stopwords, prefix fallback) bumps `retrieval_recall_at_k` on the held-out set; the substring-match scorer remains conservative per proposal limitations.

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
