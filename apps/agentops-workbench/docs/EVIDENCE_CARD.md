# Evidence Card — AgentOps Workbench

## What we built

A LangGraph / FastAPI support-ops agent integrating custom document MCP server + pinned @modelcontextprotocol/server-filesystem (fixture-only scope). Exposes a REST surface (POST /v1/runs, /v1/runs/{id}/cancel, /v1/actions) with JWT auth and a Streamlit UI skeleton.

## What we measured

Held-out evaluation: 6 cases x 2 trials x 2 topologies = 24 runs, identical corpus / prompt / budget / permissions across topologies. See `experiments/held-out-v1/` after running `uv run python -m agentops_workbench.experiments.run_held_out`.

## What we shipped

- Topology: **fixed graph** as the default per ADR-0006
- Provider: `minimax` (live) per ADR-0003 + `local-fake` (CI)
- MCP spec revision: `2026-07-28` per ADR-0002
- Held-out set: 6 cases, content-hashed into `HELD_OUT_SHA256.txt`

## Personal contributions

All design decisions, code, tests, and 7-step implementation plan are in this repo's git history (commits authored by sh-ai-x <tkd1496@gmail.com>).

## Limitations

- Held-out set is 6 cases (small by design; proposal explicitly labels this "illustrative, not statistically settled").
- The 24-run experiment was the dry-run against `provider=local-fake`. Live numbers require a `provider=minimax` run with the API key from `dev-harness-kit/.env`.
- Topology comparison does not vary temperature / model / corpus; any drift invalidates the comparison (R4 invariant).

## How to reproduce

```
```bash
cd ~/dev/agentops-workbench
uv sync --extra dev
cp .env.example .env
# edit .env: paste MINIMAX_API_KEY from /Users/sanghee/dev/dev-harness-kit/.env
AGENTOPS_PROVIDER=minimax uv run python -m agentops_workbench.experiments.run_held_out
```

## Resumé bullet (from proposal template)

> Built a LangGraph/FastAPI support agent integrating 2 MCP servers; compared 2 workflow configurations on 6 scenarios and shipped the fixed graph based on task success, recovery, latency and cost.

## References

- Proposal: `docs/proposals/agentops-workbench-proposal.md`
- Plan: dev-harness-kit `.dev-kit/round-1/phases/build/step{1..7}.md`
- ADRs: `docs/adr/0001..0006-*.md`
- Held-out artifacts (after running the experiment): `experiments/held-out-v1/`
