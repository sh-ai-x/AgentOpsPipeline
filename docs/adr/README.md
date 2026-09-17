# Architecture Decision Records (project root)

> This directory is the project-level **index** for the ADR catalogue. The
> actual ADRs live inside the application that owns the runtime —
> `apps/agentops-workbench/docs/adr/` — because every decision below is
> about how the agent runs, what providers it may use, what data it
> trains on, and how the held-out experiment is structured. None of the
> ADRs are about the monorepo itself (the bootstrap, the dev-kit install,
> the CI templates); those are governed by `.dev-kit/ci-config.json` and
> the upstream `dev-harness-kit` repository, not by an ADR.

## Catalogue (canonical owner: `apps/agentops-workbench/docs/adr/`)

| # | Title | Status | Owner file |
|---|-------|--------|-----------|
| 0001 | LangGraph as the workflow engine | Accepted | [`../../apps/agentops-workbench/docs/adr/0001-langgraph.md`](../../apps/agentops-workbench/docs/adr/0001-langgraph.md) |
| 0002 | MCP server boundaries (stdio-only for MVP) | Accepted | [`../../apps/agentops-workbench/docs/adr/0002-mcp-boundaries.md`](../../apps/agentops-workbench/docs/adr/0002-mcp-boundaries.md) |
| 0003 | Provider abstraction (`LLMAdapter`) + cost cap | Accepted | [`../../apps/agentops-workbench/docs/adr/0003-provider-abstraction.md`](../../apps/agentops-workbench/docs/adr/0003-provider-abstraction.md) |
| 0004 | Dataset separation (dev / val / held-out) | Accepted | [`../../apps/agentops-workbench/docs/adr/0004-dataset-separation.md`](../../apps/agentops-workbench/docs/adr/0004-dataset-separation.md) |
| 0005 | Runtime safety / cost cap | Tombstone | [`0005-runtime-safety.md`](0005-runtime-safety.md) (absorbed into ADR-0003) |
| 0006 | Topology shipping choice (fixed graph) | Accepted | [`../../apps/agentops-workbench/docs/adr/0006-topology.md`](../../apps/agentops-workbench/docs/adr/0006-topology.md) |
| 0007 | Evidence-source adapter pattern (generalizes `DocumentClient`) | Accepted | [`../../apps/agentops-workbench/docs/adr/0007-evidence-source-adapter-pattern.md`](../../apps/agentops-workbench/docs/adr/0007-evidence-source-adapter-pattern.md) |
| 0008 | GitHub-URL CLI flow scope + deployment target (Fly.io) | Accepted | [`../../apps/agentops-workbench/docs/adr/0008-github-url-cli-and-deployment-target.md`](../../apps/agentops-workbench/docs/adr/0008-github-url-cli-and-deployment-target.md) |
| 0009 | oss-helper reduced to docs-only flow (GitHub issues/PRs source dropped) | Accepted | [`0009-oss-helper-docs-only-scope.md`](0009-oss-helper-docs-only-scope.md) — **misfiled**: lives at the project root, not under the canonical `apps/agentops-workbench/docs/adr/` owner directory; not yet moved |
| 0010 | Dense retrieval, hybrid fusion and CPU reranking for WikiRagAdapter — without pgvector | Accepted | [`../../apps/agentops-workbench/docs/adr/0010-dense-retrieval-and-reranking.md`](../../apps/agentops-workbench/docs/adr/0010-dense-retrieval-and-reranking.md) |
| 0011 | Real OpenTelemetry export for the wiki-chat path | Proposed | [`../../apps/agentops-workbench/docs/adr/0011-real-otel-export.md`](../../apps/agentops-workbench/docs/adr/0011-real-otel-export.md) |

## The ADR-0005 gap

There is **no** `0005-*.md` in `apps/agentops-workbench/docs/adr/`. The number
was reserved during the original planning round (see
`.dev-kit/round-1/phases/build/step1.md` §1.4 and `step3.md` §3.2) for a
"runtime safety / cost cap" decision. As the architecture solidified, that
decision collapsed into ADR-0003's cost-cap section — the `LLMAdapter` per-call
cap plus the cumulative-spend check is the single control surface, and it did
not warrant a separate document.

The number is preserved here as a **tombstone** ([`0005-runtime-safety.md`](0005-runtime-safety.md))
so the surrounding ADRs are not renumbered and existing cross-references stay
stable. If a future decision needs a number, **use the next free integer**
(0007+) — do not backfill 0005.

## Status legend

- **Accepted** — the decision is in force; the surrounding code and tests reflect it.
- **Superseded** — a later ADR (linked in the body) overrode this one.
- **Tombstone** — preserved for numbering stability; the original decision was folded into a different ADR.

## Adding a new ADR

1. Pick the next free integer: `ls apps/agentops-workbench/docs/adr/`.
2. Write `apps/agentops-workbench/docs/adr/NNNN-<slug>.md` — that directory is
   the canonical owner, because the ADRs document application behaviour.
3. Add the row to the catalogue table above.
4. If the ADR is referenced from a phase, link it from that phase's
   `phases/<NN-slug>/index.md` "Cross-references" section too.
5. Open a PR; the dev-kit review gate checks ADR-format compliance
   (Status / Decision / Consequences sections).

## Format template

```markdown
# ADR-NNNN: <title>

## Status

Accepted (YYYY-MM-DD) | Superseded by ADR-MMMM | Tombstone (see ADR-MMMM).

## Context

<one paragraph: what problem triggered this decision?>

## Decision

<one paragraph: what did we choose?>

## Consequences

- <positive consequence>
- <negative consequence or explicit risk accepted>
- <link to the implementation or test that locks the decision in>
```
