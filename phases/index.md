# Phases — AgentOpsPipeline

> Retrospective phase index for the AgentOps Workbench build. Each phase is a
> proposal-anchored milestone with an exit criterion and a set of shipped
> artefacts under `apps/agentops-workbench/`. This file is the root index;
> per-phase detail lives in `phases/<NN-slug>/index.md`.
>
> **Status: all seven phases are implemented and merged.** The workbench was
> imported into this monorepo in PR #8 (`feat/agentops-workbench`); the live
> held-out and 3-prompt experiments have been run against `provider=minimax`
> (`MiniMax-M3`). See
> [`../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
> for the shipped summary.

## Phases

| # | Slug | Title | Step plan | Weeks (est.) | Exit criterion |
|---|------|-------|-----------|--------------|----------------|
| 0 | [00-bootstrap](00-bootstrap/) | Repo bootstrap, ADRs, scope fixtures, pilot dataset | `step1.md` | 0.5 | Another developer can score the pilot without guessing what "good" means |
| 1 | [01-runnable-agent](01-runnable-agent/) | Runnable agent + FastAPI + local-fake adapter | `step2.md` | 1.5 | Normal task completes; missing evidence produces a supported refusal; failed tool is visible |
| 2 | [02-mcp-integration](02-mcp-integration/) | MCP document server + filesystem pin + recovery | `step3.md` | 1.0 | Tools work through the protocol and a repeated action does not duplicate the mock effect |
| 3 | [03-benchmark-prompts](03-benchmark-prompts/) | 30-case dataset + scorers + prompt experiments | `step4.md` | 1.0 | Every promoted case is traceable and held-out data has not influenced tuning |
| 4 | [04-topology-experiments](04-topology-experiments/) | Topology variants + planner/executor | `step5.md` | 1.0 | Selection follows measured utility; a simpler workflow may win |
| 5 | [05-delivery](05-delivery/) | OTel, regression, Docker Compose, runbook | `step6.md` | 1.5 | A clean setup works; seeded regression fails CI; traces do not expose synthetic secrets |
| 6 | [06-held-out-portfolio](06-held-out-portfolio/) | Held-out evaluation + evidence card + demo | `step7.md` | 1.0 | A reviewer can reproduce an offline failure and inspect the basis for the shipping decision |

Phase numbers are 0-indexed (they match the proposal); the step-plan files are
1-indexed (`step1.md` = Phase 0). Estimates are the original plan values, not
measured effort.

## Source of truth

The detailed build plan (`PRD.md`, `phases/build/index.json`,
`phases/build/step1..step7.md`) lives under `.dev-kit/round-1/`, which is a
**local, `.gitignore`d planning artefact** — it is not in version control and
does not appear on GitHub. This `phases/` tree is the tracked, self-contained
promotion of it for non-build consumers (operators, code reviewers, hand-off
readers): each `phases/<NN-slug>/index.md` carries that phase's deliverables,
what actually shipped, and links to the tracked anchors (the proposal and
`apps/agentops-workbench/`).

The tracked anchors are:

- [`../docs/proposals/agentops-workbench-proposal.md`](../docs/proposals/agentops-workbench-proposal.md) — the design proposal (phase sections `§"Phase 0".."Phase 6"`).
- [`../apps/agentops-workbench/`](../apps/agentops-workbench/) — the implementation.
- [`../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../apps/agentops-workbench/docs/EVIDENCE_CARD.md) — what was built and measured.

## Pins (project-wide)

- Python `>=3.10`
- `langgraph==1.2.11`, `langchain-core>=0.3`
- `mcp==2.2.0` (SDK); MCP spec revision `2026-07-28` (pinned in the `initialize` handshake)
- `provider=minimax` / model `MiniMax-M3` (live); `provider=local-fake` (CI, deterministic)
- Methodology: TDD per step; a regression test is required per step
- Branch protection: PR review required; no force-push to `main`

## How it actually shipped

The original plan called for one `feat/NN-*` branch per phase off a standalone
`~/dev/agentops-workbench` repo. In practice the workbench was built in that
separate repo and then consolidated into this monorepo:

| PR | What landed |
|----|-------------|
| #1 | AgentOps Workbench design proposal (`docs/proposals/agentops-workbench-proposal.md`) |
| #2 | MiniMax pinned as the default live provider |
| #5 -> #8 | `apps/agentops-workbench/` import (Phases 0–6), security gate dropped, review criticals fixed |
| #10–#14 | Post-import fixes: usage persistence, lexical retrieval, prompt-aware `local-fake`, Streamlit token UX |

## ADRs

Architecture decisions are owned by `apps/agentops-workbench/docs/adr/` (they
describe how the agent runs, not the monorepo layout). Project-level index:
[`../docs/adr/README.md`](../docs/adr/README.md).

- [ADR-0001 LangGraph](../apps/agentops-workbench/docs/adr/0001-langgraph.md) — workflow engine choice
- [ADR-0002 MCP boundaries](../apps/agentops-workbench/docs/adr/0002-mcp-boundaries.md) — stdio scope; Streamable-HTTP deferred
- [ADR-0003 Provider abstraction](../apps/agentops-workbench/docs/adr/0003-provider-abstraction.md) — `LLMAdapter`; provider allow-list; cost cap
- [ADR-0004 Dataset separation](../apps/agentops-workbench/docs/adr/0004-dataset-separation.md) — 18/6/6 frozen split
- ADR-0005 — *tombstone*, see [`../docs/adr/0005-runtime-safety.md`](../docs/adr/0005-runtime-safety.md) (absorbed into ADR-0003)
- [ADR-0006 Topology](../apps/agentops-workbench/docs/adr/0006-topology.md) — fixed graph as the default

## Status

- **Phases 0–6:** implemented in `apps/agentops-workbench/`, merged via PR #8.
- **Local gates:** `uv run pytest` green, `uv run ruff check` clean (the app README tags 137 tests; `docs/EVIDENCE_CARD.md` reports 144 after the post-import fixes).
- **Live experiments:** held-out (24 runs) and 3-prompt comparison (18 runs) run
  against `MiniMax-M3` — 42 runs, ~$0.03 total. `v3_minimal` published as the
  unsuccessful change per the proposal.
- **Known limitation:** the substring-match task scorer is conservative;
  `task_success` reads ~0% on several runs whose answers are semantically
  correct. Tracked in `apps/agentops-workbench/docs/EVIDENCE_CARD.md`.

See [`../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
for the shipped summary and
[`../apps/agentops-workbench/docs/RUNBOOK.md`](../apps/agentops-workbench/docs/RUNBOOK.md)
for operations.
