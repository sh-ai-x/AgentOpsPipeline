# Phases — AgentOpsPipeline

> Phase index for the AgentOpsPipeline work. Each phase corresponds to a
> proposal-anchored milestone with one shipped step (its `.dev-kit/round-1/`
> `step<N>.md` plan), an exit criterion, and the matching `feat/NN-*` branch.
> All phase data flows from `apps/agentops-workbench/`. This file is the
> root index; per-phase indexes live in `phases/<NN-slug>/index.md`.

## Phases

| # | Slug | Title | Branch | Weeks | Exit |
|---|------|-------|--------|-------|------|
| 0 | [00-bootstrap](00-bootstrap/) | Repo bootstrap, ADRs, scope fixtures, pilot dataset | `feat/00-bootstrap` | 0.5 | Another developer can score the pilot without guessing what "good" means |
| 1 | [01-runnable-agent](01-runnable-agent/) | Runnable agent + FastAPI + local-fake adapter | `feat/01-runnable-agent` | 1.5 | Normal task completes; missing evidence produces a supported refusal; failed tool is visible |
| 2 | [02-mcp-integration](02-mcp-integration/) | MCP document server + filesystem pin + recovery | `feat/02-mcp-integration` | 1.0 | Tools work through the protocol and a repeated action does not duplicate the mock effect |
| 3 | [03-benchmark-prompts](03-benchmark-prompts/) | 30-case dataset + scorers + prompt experiments | `feat/03-benchmark-prompts` | 1.0 | Every promoted case is traceable and held-out data has not influenced tuning |
| 4 | [04-topology-experiments](04-topology-experiments/) | Topology variants + planner/executor | `feat/04-topology-experiments` | 1.0 | Selection follows measured utility; a simpler workflow may win |
| 5 | [05-delivery](05-delivery/) | OTel, regression, Docker Compose, runbook | `feat/05-delivery` | 1.5 | A clean setup works; seeded regression fails CI; traces do not expose synthetic secrets |
| 6 | [06-held-out-portfolio](06-held-out-portfolio/) | Held-out evaluation + evidence card + demo | `feat/06-held-out-portfolio` | 1.0 | A reviewer can reproduce an offline failure and inspect the basis for the shipping decision |

## Source of truth

The detailed step plan for every phase lives in two places that must stay in sync:

1. **Authoritative machine-readable plan**: `.dev-kit/round-1/phases/build/index.json` — used by `/dev-kit:plan` and `/dev-kit:build` to drive the build.
2. **Human-readable step docs**: `.dev-kit/round-1/phases/build/step<N>.md` — the per-step blueprint the implementer works from.

The `phases/` tree at this root is the *promoted* index for non-build consumers (operators, code reviewers, handoff readers). It mirrors the build plan with one additional artefact per phase: a per-phase `index.md` that points at the canonical plan + the shipped artefact in `apps/agentops-workbench/`.

## Pins (project-wide)

- Python `>=3.10`
- `langgraph==1.2.11`
- `mcp==2.2.0` (SDK); MCP spec `2026-07-28`
- `provider=minimax` (live), `provider=local-fake` (CI)
- Methodology: TDD per step; regression test required per step
- Branch protection: PR review required; no force-push to `main`

## ADRs (architecture decision records)

Project-level architecture decisions are recorded in `apps/agentops-workbench/docs/adr/`. The catalogue:

- [ADR-0001 LangGraph](../apps/agentops-workbench/docs/adr/0001-langgraph.md) — workflow engine choice
- [ADR-0002 MCP boundaries](../apps/agentops-workbench/docs/adr/0002-mcp-boundaries.md) — stdio scope; Streamable-HTTP deferred
- [ADR-0003 Provider abstraction](../apps/agentops-workbench/docs/adr/0003-provider-abstraction.md) — `LLMAdapter`; provider allow-list
- [ADR-0004 Dataset separation](../apps/agentops-workbench/docs/adr/0004-dataset-separation.md) — 18/6/6 frozen split
- [ADR-0006 Topology](../apps/agentops-workbench/docs/adr/0006-topology.md) — fixed graph as default

There is intentionally no ADR-0005 in the project-level catalogue; see `apps/agentops-workbench/docs/adr/README.md` for the gap explanation (it was reserved for a runtime-safety / budget-cap decision that was ultimately absorbed into ADR-0003's "cost cap" section — the number is preserved as a tombstone so the surrounding ADRs are not renumbered).

## Status

- Phases 0–6: implemented in `apps/agentops-workbench/` (imported into this monorepo via PR #5 `chore/consolidate-workbench`).
- Held-out evaluation: dry-run complete (`provider=local-fake`); live run pending `provider=minimax` API key.

See `apps/agentops-workbench/docs/EVIDENCE_CARD.md` for the shipped summary.
