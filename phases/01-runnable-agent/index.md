# 01-runnable-agent

> Phase 1 — Runnable agent + FastAPI + local-fake adapter

- **Branch:** `feat/01-runnable-agent`
- **Estimated:** 1.5 week(s)
- **Step doc:** [step-1.md](step-1.md) (canonical: `.dev-kit/round-1/phases/build/step1.md`)
- **Step branch:** `feat/01-runnable-agent`
- **Exit criterion:** Normal task completes; missing evidence produces a supported refusal; failed tool is visible

## Title

Runnable agent + FastAPI + local-fake adapter

## Deliverables

- `LLMAdapter` ABC + `local-fake` / `minimax` adapters\n- fixed LangGraph workflow (retrieve → classify → answer/refuse/clarify)\n- FastAPI `/v1/runs` + `/v1/runs/{id}` + JWT auth\n- mock ticket ledger\n- Streamlit skeleton

## Cross-references

- Source proposal: `docs/proposals/agentops-workbench-proposal.md`
- Implemented in: `apps/agentops-workbench/`
- Step plan (authoritative): `.dev-kit/round-1/phases/build/step1.md`
- Step plan (mirror): `phases/01-runnable-agent/step-1.md`
