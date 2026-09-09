# Evidence Card — AgentOps Workbench

## Where this lives

This project was originally built in a standalone GitHub repo
(`sh-ai-x/agentops-workbench`, now archived). It now lives at
`apps/agentops-workbench/` inside `sh-ai-x/AgentOpsPipeline`. The
surrounding dev-harness-kit (hooks/, lib/, bin/, tools/) is the
Claude Code tooling used to ship this project.

## What we built

A LangGraph / FastAPI support-ops agent integrating a custom document
MCP server + pinned `@modelcontextprotocol/server-filesystem`
(fixture-only scope). Exposes a REST surface (POST /v1/runs, GET
/v1/runs/{id}, POST /v1/runs/{id}/cancel, POST /v1/actions) with JWT
auth and a Streamlit UI skeleton.

## What we measured

Held-out evaluation: 6 cases x 2 trials x 2 topologies = 24 runs,
identical corpus / prompt / budget / permissions across topologies.
Results at `experiments/held-out-v1/`.

Local-fake dry-run (provider=local-fake, deterministic) wrote 24
outcomes. Live numbers require a `provider=minimax` run with the API
key sourced from the dev-harness-kit `.env`.

## What we shipped

- Topology: **fixed graph** as the default per ADR-0006
- Provider: `minimax` (live) per ADR-0003 + `local-fake` (CI)
- MCP spec revision: `2026-07-28` per ADR-0002
- Held-out set: 6 cases, content-hashed into `HELD_OUT_SHA256.txt`

## Personal contributions

All design decisions, code, tests, and the 7-step implementation plan
are in this repo's git history (commits authored by
`sh-ai-x <tkd1496@gmail.com>`).

## Limitations

- Held-out set is 6 cases (small by design; proposal explicitly labels
  this "illustrative, not statistically settled").
- Topology comparison does not vary temperature / model / corpus; any
  drift invalidates the comparison (R4 invariant).
- Live experiment was deferred; the local-fake dry-run populated the
  outcomes schema but cannot speak to live model quality.

## How to reproduce

```bash
cd apps/agentops-workbench
uv sync --extra dev
cp .env.example .env
# paste MINIMAX_API_KEY from /Users/sanghee/dev/dev-harness-kit/.env
AGENTOPS_PROVIDER=minimax uv run python -m agentops_workbench.experiments.run_held_out
```

## Resumé bullet (from proposal template)

> Built a LangGraph/FastAPI support agent integrating 2 MCP servers;
> compared 2 workflow configurations on 6 held-out scenarios and shipped
> the fixed graph based on task success, recovery, latency and cost.

## References

- Proposal: `../../docs/proposals/agentops-workbench-proposal.md`
- Plan: `../../../.dev-kit/round-1/{PRD.md, phases/build/step1..7.md}`
- ADRs: `docs/adr/0001..0006-*.md`
- Held-out artifacts: `experiments/held-out-v1/`
