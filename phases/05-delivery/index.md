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

**Post-launch patches** (since PR #8):
- PR #12: `GET /_debug/retrieve?task=<text>` endpoint (no auth; dev-only) — operator can verify retrieval before running a full `/v1/runs` cycle.
- PR #13: Streamlit UI hardened — the Bearer-token field is hidden when `AGENTOPS_ALLOW_DEV_TOKEN=1` is set; the dev-token path auto-mints. Out-of-band mode shows an explicit `Clear` button. Eliminates the 'stale pasted token → HTTP 401' loop.
- PR #15: 6 PNG screenshots of the running UI captured via Playwright + system Chrome; `scripts/screenshot_streamlit.py` regenerator; `scripts/print_metrics.py` CLI; new `GET /_debug/metrics` endpoint with 30s-TTL cache and provider guard (403 unless `provider=local-fake` or `AGENTOPS_ALLOW_DEBUG_METRICS=1`).

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
