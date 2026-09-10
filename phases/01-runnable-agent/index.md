# 01-runnable-agent

> Phase 1 — Runnable agent + FastAPI + local-fake adapter

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Phase 1"
- **Canonical step plan:** `.dev-kit/round-1/phases/build/step2.md` — local planning artefact, not tracked in git (`.dev-kit/round-1/` is `.gitignore`d). This page is the tracked, self-contained promotion of it.
- **Estimated:** 1.5 weeks (original plan value, not measured effort)
- **Exit criterion:** Normal task completes; missing evidence produces a supported refusal; failed tool is visible
- **Status:** shipped — merged into `apps/agentops-workbench/` via PR #8
- **Build output:** [`step2-output.json`](step2-output.json) — audit vs. acceptance criterion: **AC NOT met** (runs issue no tool calls; refusal only vacuously tested; approval→publish not wired). See [`../build-report.md`](../build-report.md).

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
- **Gaps (see `step2-output.json`):** `_classify` is a keyword heuristic and never returns `clarify`; the run path issues no tool calls, so "failed tool is visible" is unimplemented; `/v1/actions` mints a nonce but never calls `TicketLedger.publish()`, so run → draft → approve → publish is not connected

**Post-launch patches** (since PR #8):
- PR #10: every `LLMAdapter` now populates `Usage.total_tokens`/`prompt_tokens`/`completion_tokens`/`cost_usd` (`_last_usage` field); `_execute_run` writes those onto the `Run` row so `/v1/runs/{id}` surfaces real metrics instead of zeros.
- PR #10: `_retrieve_docs` normalizes tokens (regex split, lowercase, common-stopword filter, 6-char prefix fallback for tokens ≥ 7 chars) — `checkpointing` matches `checkpointer`, `postgresql` matches `postgrescheckpointer`.
- PR #12: `LocalFakeAdapter.chat()` picks a scripted response by keyword routing (`langgraph`+`checkpoint` → PostgresCheckpointer; `postgres`+`sqlite` → comparison). `fixtures/llm/scripts/default.jsonl` still consulted for unrelated queries.
- PR #12: new `GET /_debug/retrieve?task=<text>` web-debug surface — returns the doc stems + snippets the fixed graph would surface, no auth required (dev-only).
- PR #14: `LocalFakeAdapter.chat()` parses the `Retrieved docs:` block out of the prompt, composes a structured answer (intro + cited stem + quoted passage + 'see also' for supporting docs + source attribution) so the dev output reads like a real LLM answer, not a hardcoded line.

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
