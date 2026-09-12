# Phases — AgentOpsPipeline

> Retrospective phase index for the AgentOps Workbench build. Each phase is a
> proposal-anchored milestone with an exit criterion and a set of shipped
> artefacts under `apps/agentops-workbench/`. This file is the root index;
> per-phase detail lives in `phases/<NN-slug>/index.md`.
>
> **Status: all seven phases were merged as surface, not as satisfied
> acceptance criteria.** [`build-report.md`](build-report.md) is the
> authoritative status — it found 2 of 7 cleanly met on first audit
> (2026-09-11); PR #20/#21 (2026-09-13) closed the root-cause tool-dispatch
> stub for the `planner_executor` topology, moving several steps from "fully
> unmet" to "partial," but none has been re-verified as a clean **yes** yet,
> and the held-out re-run is still pending. Read `build-report.md` before
> trusting any phase-complete claim in this file. The workbench was imported
> into this monorepo in PR #8 (`feat/agentops-workbench`); the live held-out
> and 3-prompt experiment *numbers* below predate PR #20/#21 and have not
> been refreshed. See
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

## Build record

`/dev-kit:build` was never run in this monorepo (the workbench was built
standalone and imported via PR #8), so no per-step `step<N>-output.json` was
ever emitted. [`build-report.md`](build-report.md) **audits the merged tree
against each step's acceptance criterion** and each phase carries a
`phases/<NN-slug>/step<N>-output.json` with its verdict.

Result (2026-09-11): **2 of 7 acceptance criteria are cleanly met** (step 1
bootstrap, step 4 dataset). Steps 2, 3, 5, 6 ship a real surface but do not
satisfy their AC as written; step 7 is reproducible but rests on zero
primary-metric signal. The common cause: the agent never issues tool calls —
`graph/single_agent.py` and `graph/planner_executor.py` both carried
`# Tool dispatch is a stub for MVP; step 6 wires real MCP calls`.

**Update 2026-09-13:** [PR #20](https://github.com/sh-ai-x/AgentOpsPipeline/pull/20)
+ [PR #21](https://github.com/sh-ai-x/AgentOpsPipeline/pull/21) removed
`planner_executor.py`'s half of that stub — it now genuinely calls
`search_docs`/`read_document` and honestly reports `get_issue` as
unsupported (no backing data source exists for it) instead of no-op'ing.
`single_agent.py`'s stub is untouched. Net: steps 3/5/6 moved from "fully
unmet" to "real for one of two topologies, not yet re-verified against
their AC"; the held-out re-run (step 7) has not happened. Full breakdown,
including what's still open, in [`build-report.md`](build-report.md).

Gates re-run 2026-09-13 on `main`: `uv run pytest -q` → **177 passed, 0
failed**. (2026-09-11 baseline: 153 passed, 1 failed of 154 collected — that
one failure was a `.env`-presence test-isolation artifact, not reproducing
in a fresh worktree.) `uv run ruff check .` → 5 pre-existing findings, all in
`scripts/*.py`, unrelated to #20/#21. See [`build-report.md`](build-report.md).

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

- **Phases 0–6:** merged into `apps/agentops-workbench/` via PR #8 — the
  [`build-report.md`](build-report.md) audit found only steps 1 and 4 fully
  satisfy their acceptance criteria (2026-09-11); PR #20/#21 (2026-09-13)
  closed the `planner_executor` half of the tool-execution gap behind
  steps 2/3/5/6, `single_agent`'s half is still open, and step 7 still
  needs a re-run — see `build-report.md` for the current per-step verdicts.
- **Local gates (re-run 2026-09-13, `main` post PR #20/#21):** `uv run pytest`
  177/177 passed, `uv run ruff check` 5 pre-existing findings (unrelated,
  `scripts/*.py`) — full breakdown in [`build-report.md`](build-report.md).
- **Live experiments:** held-out (24 runs) and 3-prompt comparison (18 runs) ran
  against `MiniMax-M3` — 42 runs, ~$0.03 total — **before** PR #20/#21;
  `v3_minimal` published as the unsuccessful change per the proposal. Not
  yet re-run against the current tool-wired `planner_executor`.
- **Known limitations:** (1) tool execution is now real for `planner_executor`
  (PR #21) but still stubbed in `single_agent` (`# stub for MVP`), so the
  held-out `tool_correctness` numbers above (0/24) predate the fix and are
  stale until re-run. (2) The substring-match task scorer is also
  conservative. (3) `EVIDENCE_CARD.md`'s tool/test counts were corrected
  2026-09-13 (2 real tools, not 5; 177 tests, not 144).

See [`../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
for the shipped summary and
[`../apps/agentops-workbench/docs/RUNBOOK.md`](../apps/agentops-workbench/docs/RUNBOOK.md)
for operations.
