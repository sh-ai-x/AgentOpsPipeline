# 05-delivery

> Phase 5 — OTel, regression, Docker Compose, runbook

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Phase 5"
- **Canonical step plan:** `.dev-kit/round-1/phases/build/step6.md` — local planning artefact, not tracked in git (`.dev-kit/round-1/` is `.gitignore`d). This page is the tracked, self-contained promotion of it.
- **Estimated:** 1.5 weeks (original plan value, not measured effort)
- **Exit criterion:** A clean setup works; seeded regression fails CI; traces do not expose synthetic secrets
- **Status:** shipped — merged into `apps/agentops-workbench/` via PR #8
- **Build output:** [`step6-output.json`](step6-output.json) — audit vs. acceptance criterion: **AC NOT met** (MCP wiring deferred here never done; 1 regression test fails in dev env). See [`../build-report.md`](../build-report.md).

## Deliverables (planned)

- OTel exporter with credential redaction (`api_key`, `authorization`, `bearer`, `password`)
- One failed case turned into the smallest failing regression test
- Docker Compose stack; Alembic migrations; offline CI
- Operator runbook

## What shipped

- `src/agentops_workbench/observability/otel.py` — spans + redaction
- `alembic/`, `docker/docker-compose.yml` (postgres + api + worker + streamlit + mcp-document)
- `docs/RUNBOOK.md`
- Async worker via `concurrent.futures` (production-swappable to arq + Redis)
- **Gaps (see `step6-output.json`):** the "step 6 wires real MCP calls" work that the step-5 stubs deferred here was never done; the seeded regression suite has one failing test in the dev env (`.env`-sensitive isolation); "a clean docker setup works" is not covered by any test or CI job

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
