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
>
> **Amended 2026-09-13.** "All seven phases implemented and merged" above
> refers to Phases **0–6** and is left as written; read it with
> [`build-report.md`](build-report.md), which finds only 2 of 7 acceptance
> criteria cleanly met. A new **Phase 7** was added by the portfolio pivot
> to open-source maintainer tooling (proposal §"Pivot (2026-09-13)",
> [ADR-0007](../apps/agentops-workbench/docs/adr/0007-evidence-source-adapter-pattern.md)).
>
> **Amended again, same day.** Phase 7 is **partially built**, not
> "not started" — [PR #34](https://github.com/sh-ai-x/AgentOpsPipeline/pull/34)
> (merged) implements all five adapters, 223 tests passing; the
> registry/config layer and Pillar 2's eval layer are the remaining gaps
> (see [`07-adapter-pattern-pivot/index.md`](07-adapter-pattern-pivot/index.md)'s
> reconciled deliverables list). A new **Phase 8** narrows the product
> scope to one flagship GitHub-URL CLI flow and a real deployment target
> (proposal §"Update 2 (2026-09-13)",
> [ADR-0008](../apps/agentops-workbench/docs/adr/0008-github-url-cli-and-deployment-target.md))
> and is **not started**.

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
| 7 | [07-adapter-pattern-pivot](07-adapter-pattern-pivot/) | Evidence-source adapter generalization + OSS-maintainer pillars | *(no `.dev-kit` step plan — post-pivot, planned in the proposal)* | 2.0 | A run against a GitHub issue returns a draft whose every citation resolves to an `EvidenceRef` from a registered adapter, with the docs-corpus suite passing unchanged and `retrieval_recall` reported per `source_kind` |
| 8 | [08-deployable-mvp](08-deployable-mvp/) | One flagship GitHub-URL CLI flow + deployable backend | *(no `.dev-kit` step plan — planned in the proposal §"Update 2")* | not yet sized | A reviewer runs `agentops-oss-helper <public-repo-url> --issue N` and gets a grounded answer with zero manual setup beyond one token env var; the backend passes a scripted `/v1/runs` smoke test with Streamlit absent from the environment |

Phase numbers are 0-indexed (they match the proposal); the step-plan files are
1-indexed (`step1.md` = Phase 0). Estimates are the original plan values, not
measured effort.

**Phases 7 and 8 are post-pivot.** They are numbered into the same
0-indexed sequence because they continue the same proposal and the same
codebase — the pivot amends the narrative, not the architecture. Neither has
a `.dev-kit/round-1/phases/build/step<N>.md` ancestor (that planning round
covered steps 1–7 = Phases 0–6 only), so neither carries a
`step<N>-output.json`; their plans live in
[`../docs/proposals/agentops-workbench-proposal.md`](../docs/proposals/agentops-workbench-proposal.md)
§"Pivot (2026-09-13)" / §"Update 2 (2026-09-13)" and
[ADR-0007](../apps/agentops-workbench/docs/adr/0007-evidence-source-adapter-pattern.md) /
[ADR-0008](../apps/agentops-workbench/docs/adr/0008-github-url-cli-and-deployment-target.md)
respectively.

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

Result: **2 of 7 acceptance criteria are cleanly met** (step 1 bootstrap, step 4
dataset). Steps 2, 3, 5, 6 ship a real surface but do not satisfy their AC as
written; step 7 is reproducible but rests on zero primary-metric signal. The
common cause: the agent never issues tool calls — `graph/single_agent.py` and
`graph/planner_executor.py` both carry `# Tool dispatch is a stub for MVP; step
6 wires real MCP calls`, and step 6 never did that wiring. So the MCP servers
(step 3) are unreachable from a run, the topology comparison (step 5) is between
tool-less generators, and every held-out run (step 7) reports
`tool_correctness: 0.0`.

Gates re-run 2026-09-11: `uv run pytest -q` → 153 passed, 1 failed (154
collected); `uv run ruff check .` → clean. The one failure
(`test_has_insecure_jwt_secret_flags_default_and_short`) is a test-isolation
defect (`Settings()` reads a local `.env` with a strong `AGENTOPS_JWT_SECRET`)
and passes in clean CI. See [`build-report.md`](build-report.md).

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
- [ADR-0006 Topology](../apps/agentops-workbench/docs/adr/0006-topology.md) — fixed graph as the default (scoped to `DocsCorpusAdapter` by ADR-0007)
- [ADR-0007 Evidence-source adapter pattern](../apps/agentops-workbench/docs/adr/0007-evidence-source-adapter-pattern.md) — `DocumentClient` → `EvidenceSourceAdapter`; wiki / GitHub-issue / security-log / incident-log adapters (2026-09-13)
- [ADR-0008 GitHub-URL CLI flow + deployment target](../apps/agentops-workbench/docs/adr/0008-github-url-cli-and-deployment-target.md) — `oss_triage` topology; Fly.io + SQLite-on-volume deployment (2026-09-13)

## Status

- **Phases 0–6:** merged into `apps/agentops-workbench/` via PR #8 — but the [`build-report.md`](build-report.md) audit finds only steps 1 and 4 fully satisfy their acceptance criteria; steps 2/3/5/6 have unwired tool execution and step 7 rests on zero task-success signal.
- **Local gates (re-run 2026-09-11):** `uv run pytest` 153/154 (1 env-only failure), `uv run ruff check` clean — full breakdown in [`build-report.md`](build-report.md).
- **Live experiments:** held-out (24 runs) and 3-prompt comparison (18 runs) run
  against `MiniMax-M3` — 42 runs, ~$0.03 total. `v3_minimal` published as the
  unsuccessful change per the proposal.
- **Known limitations:** (1) tool execution is stubbed in the `single_agent` /
  `planner_executor` topologies (`# stub for MVP`), so no agent run issues a tool
  call and `tool_correctness` is 0/24 on the held-out set. (2) The substring-match
  task scorer is also conservative. (3) `EVIDENCE_CARD.md` overstates the tool
  count (5 claimed, 2 real) and the test count (144 claimed, 154 collected).
- **Phase 7 (added 2026-09-13, partially built):** the portfolio narrative
  pivoted from support-operations to open-source maintainer tooling; the
  evidence layer generalizes from a single `DocumentClient` over
  `fixtures/docs/` to an `EvidenceSourceAdapter` Protocol with wiki /
  GitHub-issue / security-log / incident-log / ticket-system adapters.
  Architecture (LangGraph topologies, MCP tool execution, FastAPI surface,
  benchmark harness) is unchanged. All five adapters are implemented and
  tested in [PR #34](https://github.com/sh-ai-x/AgentOpsPipeline/pull/34)
  (merged, 223 tests passing) — the registry/config layer and Pillar 2's
  eval layer remain open. See
  [`07-adapter-pattern-pivot/index.md`](07-adapter-pattern-pivot/index.md),
  [ADR-0007](../apps/agentops-workbench/docs/adr/0007-evidence-source-adapter-pattern.md),
  and proposal §"Pivot (2026-09-13)". Note that ADR-0007 scopes ADR-0006's
  fixed-graph selection to the docs corpus, so the shipping topology is an
  open question per evidence source.
- **Phase 8 (added 2026-09-13, not started):** narrows the product scope
  to one flagship flow — `agentops-oss-helper <github-repo-url>` wiring
  `WikiRagAdapter` + `GitHubIssueAdapter` (two of Phase 7's five) into a
  new `oss_triage` topology — plus a real deployment target (Fly.io,
  SQLite on a volume, ~$2–6/month) and a falsifiable backend/frontend
  split (Streamlit moves to an optional extra; the deploy smoke test must
  pass without it installed). See
  [`08-deployable-mvp/index.md`](08-deployable-mvp/index.md) and
  [ADR-0008](../apps/agentops-workbench/docs/adr/0008-github-url-cli-and-deployment-target.md).

See [`../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
for the shipped summary and
[`../apps/agentops-workbench/docs/RUNBOOK.md`](../apps/agentops-workbench/docs/RUNBOOK.md)
for operations.
