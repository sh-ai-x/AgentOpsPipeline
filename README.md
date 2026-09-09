# AgentOpsPipeline

Personal Claude Code tooling for shipping software projects end-to-end.
This repo combines the **dev-harness-kit** (a Claude Code plugin
marketplace + meta-harness for shipping work) with a real shipped
project (`apps/agentops-workbench/`) that exercises the harness end-to-end.

## What's in here

```
AgentOpsPipeline/
  apps/
    agentops-workbench/   # the shipped project — LangGraph + MCP support
                          # agent + 30-case benchmark (see below)
  hooks/                  # PreToolUse + PostToolUse + Stop guards
  lib/                    # Python helpers (atomic, maintenance_gate, etc.)
  scripts/                # test.sh, ci-local.sh, validate.py, ...
  bin/                    # babysit-pr-local.sh, review-local.sh, set-provider.sh
  tools/                  # skill_usage, loop_engine, linear_sync, ...
  docs/proposals/         # design proposals
  iron-laws/              # the rules the hooks enforce
  .dev-kit/               # ralph session state, hand-off docs
  AGENTS.md               # agent instructions
  CLAUDE.md               # Claude Code session config
```

## dev-harness-kit vs. agentops-workbench

The two layers have distinct portfolio roles:

| | `hooks/`, `lib/`, `bin/`, `tools/` | `apps/agentops-workbench/` |
|---|---|---|
| **What it is** | Claude Code plugin marketplace | Application built using the marketplace |
| **Reusable?** | Yes — apply to any new project | No — single-portfolio piece |
| **Audience** | Anyone shipping projects with Claude Code | Interviewers reviewing this project |
| **Standalone value** | "I built a tool to ship projects" | "I shipped a project" |

If you only want to see the application, jump to
[`apps/agentops-workbench/`](apps/agentops-workbench/). The dev-harness-kit
docs (in `hooks/`, `lib/`, `tools/`) are how this project got shipped.

## The shipped project — AgentOps Workbench

`apps/agentops-workbench/` is a LangGraph + FastAPI support-ops agent with:

- Custom document MCP server + pinned `@modelcontextprotocol/server-filesystem`
- 30-case benchmark (18 dev / 6 val / 6 held-out)
- 3 execution topologies (fixed / single-agent / planner-executor)
- OTel tracing + credential redaction
- Docker Compose stack + Alembic + offline CI
- Held-out experiment harness + evidence card

See `apps/agentops-workbench/README.md` for the full Quickstart, architecture
diagram, dataset layout, and run instructions.

## Provenance

This repo is the working tree of the `sh-ai-x/dev-harness-kit` marketplace
(renamed locally to `AgentOpsPipeline`), plus the agentops-workbench
project that was shipped end-to-end through `/dev-kit:ralph` in September
2026. Both pieces are now under one roof for portfolio reasons; the
dev-harness-kit continues to evolve independently on the upstream
`sh-ai-x/dev-harness-kit`.

## Quickstart

### Use the harness to ship a new project

```bash
# Inside a Claude Code session, after dev-kit is installed:
/dev-kit:ralph "<1-line idea>"     # walk through research → proposal → plan → ship
/dev-kit:build                     # build the staged plan
/dev-kit:babysit-pr                # poll CI until green
/dev-kit:ship                      # tag + release
```

### Run the shipped workbench locally

```bash
cd apps/agentops-workbench
uv sync --extra dev
cp .env.example .env  # paste MINIMAX_API_KEY from this repo's own .env (or the original dev-harness-kit .env)
uv run pytest -q       # 137 tests
uv run uvicorn agentops_workbench.api.server:app --port 8000
```

## CI

The repo-root `.github/workflows/ci.yml` runs `uv run ruff check .` and
`uv run pytest -q` at the root. A separate workflow at
`apps/agentops-workbench/.github/workflows/ci.yml` (proposed) would cover
the workbench subdir in isolation.

## Rules of the road

See `iron-laws/index.md` for the iron laws the hooks enforce
(no commits to main, TDD red-evidence required, worktree isolation,
destructive-confirm gate, etc.). `CLAUDE.md` summarises the rules for the
agent; `AGENTS.md` documents the project for any agent that touches it.

## License

The dev-harness-kit layer is licensed per `sh-ai-x/dev-harness-kit`. The
agentops-workbench application under `apps/` is MIT (see
`apps/agentops-workbench/LICENSE`).
