# Architecture Decision Records (project root)

> This directory is the project-level index for the ADR catalogue. The
> actual ADRs live inside the application that owns the runtime —
> `apps/agentops-workbench/docs/adr/` — because every decision below is
> about how the agent runs, what providers it can use, what data it
> trains on, and how the held-out experiment is structured. None of
> the ADRs are about the monorepo itself (the bootstrap, the dev-kit
> install, the CI templates); those are governed by `.dev-kit/ci-config.json`
> and the upstream `dev-harness-kit` repository, not by an ADR.

## Catalogue (canonical owner: `apps/agentops-workbench/docs/adr/`)

| # | Title | Owner file |
|---|-------|-----------|
| 0001 | LangGraph as the workflow engine | [apps/agentops-workbench/docs/adr/0001-langgraph.md](../../apps/agentops-workbench/docs/adr/0001-langgraph.md) |
| 0002 | MCP boundaries (stdio-only for MVP) | [apps/agentops-workbench/docs/adr/0002-mcp-boundaries.md](../../apps/agentops-workbench/docs/adr/0002-mcp-boundaries.md) |
| 0003 | Provider abstraction (`LLMAdapter`) | [apps/agentops-workbench/docs/adr/0003-provider-abstraction.md](../../apps/agentops-workbench/docs/adr/0003-provider-abstraction.md) |
| 0004 | Dataset separation (dev / val / held-out) | [apps/agentops-workbench/docs/adr/0004-dataset-separation.md](../../apps/agentops-workbench/docs/adr/0004-dataset-separation.md) |
| 0006 | Topology shipping choice | [apps/agentops-workbench/docs/adr/0006-topology.md](../../apps/agentops-workbench/docs/adr/0006-topology.md) |

## The ADR-0005 gap

There is **no** ADR-0005 in the project-level catalogue. The number was
reserved during the original planning round for a "runtime safety / cost
cap" decision. As the architecture solidified, that decision collapsed
into ADR-0003's "cost cap" section (the `LLMAdapter` per-call cap plus
`AdapterChatModel._generate`'s cumulative-spend check is the single
control surface; it did not warrant a separate ADR). The number is
preserved here as a tombstone so the surrounding ADRs are not renumbered
and existing cross-references in `apps/agentops-workbench/docs/adr/`
remain stable.

If a future decision needs a number, **use the next free integer** (0007
or beyond) — do not "backfill" 0005 to fill the tombstone.

## Status legend

- **Accepted** — the decision is in force and the surrounding code/tests
  reflect it.
- **Superseded** — a later ADR (linked in the body) overrode this one.
- **Tombstone** — preserved for numbering stability; the original
  decision was collapsed into a different ADR.

## Adding a new ADR

1. Pick the next free integer (`ls apps/agentops-workbench/docs/adr/` to
   find the highest existing).
2. Write the new file in `apps/agentops-workbench/docs/adr/NNNN-<slug>.md`
   — that directory is the canonical owner, because the ADRs document
   application behaviour, not monorepo layout.
3. Add the row to the catalogue table above.
4. If the ADR is referenced from `phases/<NN-slug>/index.md`, link it
   from the relevant phase's "Cross-references" section as well.
5. Open a PR; the dev-kit review gate will check for ADR-format
   compliance (status, decision, consequences sections).

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
- <positive consequence>
- <negative consequence or explicit risk accepted>
- <link to the implementation or test that locks the decision in>
```
