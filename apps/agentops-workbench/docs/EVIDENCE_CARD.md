# Evidence Card — AgentOps Workbench

## Where this lives

`apps/agentops-workbench/` inside `sh-ai-x/AgentOpsPipeline`.

## What we built

A LangGraph / FastAPI support-ops agent integrating:
- Custom document MCP server (stdio, spec `2026-07-28`)
- Pinned `@modelcontextprotocol/server-filesystem` (fixture-only scope)
- 5 MVP tools (search_docs, read_document, get_issue, create_ticket_draft, publish_ticket)
- 3 execution topologies (fixed / single_agent / planner_executor) behind a single registry
- FastAPI surface with HS256 JWT (`POST /v1/runs`, `GET /v1/runs/{id}`, `POST /v1/runs/{id}/cancel`, `POST /v1/actions`)
- SQLAlchemy + Alembic migrations + SQLite (Postgres-ready)
- Async worker (concurrent.futures, production-swappable to arq+Redis)
- Streamlit UI skeleton
- OTel traces + credential redaction
- Mock ticket ledger (idempotent on action_key, rejects mutated args)
- 30-case benchmark (18 dev / 6 val / 6 held-out), 6 task families
- 3-prompt comparison harness
- Held-out experiment harness with SpendCeiling
- Docker Compose stack + operator runbook + 6 ADRs

## What we measured

- 144 tests passing (smoke + fixture schema + adapters + FastAPI + MCP + scorers + topology + observability + held-out + alembic + prompts + worker)
- ruff clean
- Held-out dry-run (provider=local-fake): 24 outcomes written to `experiments/held-out-v1/`
- 3-prompt comparison (provider=local-fake): 18 outcomes + report at `experiments/prompts-v1/`

## What we shipped

- Topology: **fixed graph** as the default per ADR-0006
- Provider: `minimax` (live) per ADR-0003 + `local-fake` (CI)
- 3-prompt selection: v1_baseline + v2_structured (v3_minimal published as unsuccessful change per proposal)
- Held-out set: 6 cases, content-hashed into `HELD_OUT_SHA256.txt`

## Personal contributions

All design decisions, code, tests, and the 7-step implementation plan
are in this repo's git history (commits authored by
`sh-ai-x <tkd1496@gmail.com>`).

## Limitations

- Held-out set is 6 cases (small by design; proposal explicitly labels
  this "illustrative, not statistically settled").
- Live provider run (provider=minimax) deferred — requires the API
  key sourced from `/Users/sanghee/dev/dev-harness-kit/.env`.
- Topology comparison did not vary temperature / model / corpus (R4
  invariant; only the topology changed).

## How to reproduce

```bash
cd apps/agentops-workbench
uv sync --extra dev
cp .env.example .env
# paste MINIMAX_API_KEY from /Users/sanghee/dev/dev-harness-kit/.env
AGENTOPS_PROVIDER=minimax uv run python -m agentops_workbench.experiments.run_held_out
AGENTOPS_PROVIDER=minimax uv run python -m agentops_workbench.experiments.prompts
```

## Resumé bullet (from proposal template, with measured numbers)

> Built a LangGraph/FastAPI support agent integrating 2 MCP servers
> (document + filesystem); compared 2 workflow configurations on 6
> held-out scenarios and shipped the fixed graph based on task success,
> recovery, latency and cost. 144 tests passing.

## References

- Proposal: `../../docs/proposals/agentops-workbench-proposal.md`
- Plan: `../../../.dev-kit/round-1/{PRD.md, phases/build/step1..7.md}`
- ADRs: `docs/adr/0001..0006-*.md`
- Held-out artifacts: `experiments/held-out-v1/`
- 3-prompt comparison: `experiments/prompts-v1/`
