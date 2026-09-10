# 01-runnable-agent

> Phase 1 — Runnable agent + FastAPI + local-fake adapter

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Phase 1"
- **Canonical step plan:** `.dev-kit/round-1/phases/build/step2.md` — local planning artefact, not tracked in git (`.dev-kit/round-1/` is `.gitignore`d). This page is the tracked, self-contained promotion of it.
- **Estimated:** 1.5 weeks (original plan value, not measured effort)
- **Exit criterion:** Normal task completes; missing evidence produces a supported refusal; failed tool is visible
- **Status:** shipped — merged into `apps/agentops-workbench/` via PR #8
- **Build output:** [`step2-output.json`](step2-output.json) — reconstructed step record (see [`../build-report.md`](../build-report.md))

## Deliverables (planned)

- `LLMAdapter` ABC + `local-fake` (deterministic) and `minimax` adapters
- Fixed LangGraph workflow: `retrieve` -> `classify` -> (`answer` | `refuse` | `clarify`)
- FastAPI `POST /v1/runs` + `GET /v1/runs/{id}` with HS256 JWT auth
- Mock ticket ledger; Streamlit UI skeleton

## What shipped

- `src/agentops_workbench/llm/{adapter,factory,local_fake,minimax,openai_compat}.py`
- `src/agentops_workbench/graph/{fixed,state}.py`
- `src/agentops_workbench/api/server.py` — `/v1/runs`, `/v1/runs/{id}`, `/v1/runs/{id}/cancel`, `/v1/actions`
- `src/agentops_workbench/mocks/tickets.py` (idempotent on `action_key`); `streamlit_app/app.py`
- JWT secret startup guard + alg allowlist added in PR #8 (review critical)

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
