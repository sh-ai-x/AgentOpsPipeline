# 00-bootstrap

> Phase 0 — Repo bootstrap, ADRs, scope fixtures, pilot dataset

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Phase 0"
- **Canonical step plan:** `.dev-kit/round-1/phases/build/step1.md` — local planning artefact, not tracked in git (`.dev-kit/round-1/` is `.gitignore`d). This page is the tracked, self-contained promotion of it.
- **Estimated:** 0.5 week (original plan value, not measured effort)
- **Exit criterion:** Another developer can score the pilot without guessing what "good" means
- **Status:** shipped — merged into `apps/agentops-workbench/` via PR #8
- **Build output:** [`step1-output.json`](step1-output.json) — audit vs. acceptance criterion: **AC met** (bootstrap deliverables present + unit-tested). See [`../build-report.md`](../build-report.md).

## Deliverables (planned)

- `uv` scaffold: `pyproject.toml` (Python `>=3.10`), lockfile, `pytest` / `ruff` / `pytest-asyncio`
- `docs/scope.md` — user workflow, explicit permissions, explicit exclusions
- `fixtures/cases/schema.json` — Pydantic model dumped as JSON Schema
- 12 pilot cases (2 per family), 8 synthetic docs with attribution
- 4 ADRs: LangGraph, MCP boundaries, provider abstraction, dataset separation

## What shipped

- `apps/agentops-workbench/pyproject.toml`, `docs/scope.md`, `fixtures/cases/schema.json`
- `fixtures/cases/pilot/`, `fixtures/docs/doc-001..008-*.md`
- `docs/adr/0001-langgraph.md`, `0002-mcp-boundaries.md`, `0003-provider-abstraction.md`, `0004-dataset-separation.md`
- ADR-0005 was reserved for a runtime-safety / cost-cap decision that was folded into ADR-0003; see [`../../docs/adr/0005-runtime-safety.md`](../../docs/adr/0005-runtime-safety.md)

**Post-launch patches** (since PR #8): PR #11 added `.env.example` + `.dev-kit/gates.json` + `hooks/ralph-attended-lock.sh` — operational hygiene for the consumer repo. No build-time artefact changes.

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
