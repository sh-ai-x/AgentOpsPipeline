# ADR-0005: Runtime safety / cost cap (tombstone — absorbed into ADR-0003)

## Status

**Tombstone (2026-09-09).** The original "runtime safety / cost cap"
decision this number was reserved for was collapsed into
[ADR-0003 Provider abstraction](../apps/agentops-workbench/docs/adr/0003-provider-abstraction.md)
during Phase 1 review (see the "cost cap" section there). The number
is preserved to keep surrounding ADRs stable and to make the
"where did 0005 go?" question self-answering.

If a new runtime-safety decision needs a number, allocate the next
free integer (0007+). Do not "backfill" this slot.

## Context

During the original 7-step plan (see
`.dev-kit/round-1/phases/build/step1.md` §1.4), ADR-0005 was reserved
for "how do we stop a runaway agent from racking up unbounded LLM
spend?" — the cost cap that became the
`LLMAdapter.max_cost_usd` per-call cap plus the cumulative-spend check
in `AdapterChatModel._generate`.

## Decision

**Absorbed into ADR-0003.** The cost cap is implemented as a property of
the provider abstraction, not as a separate cross-cutting control. The
rationale at the time of the merge was:

- The cap has no consumers outside the LLM boundary (no HTTP rate
  limiter, no per-token budget in the MCP layer). Putting it on the
  adapter keeps the control co-located with the resource it gates.
- A separate "safety" ADR would have described a single `if` branch in
  a single class; the value-per-document ratio did not justify the
  separate file.

## Consequences

- ADR-0003 grew by one section ("cost cap"). It is the single source of
  truth for both provider selection and spend control.
- Cross-references in the `apps/agentops-workbench/docs/adr/` files
  point at ADR-0003 for spend control, not at this tombstone.
- Future safety controls that DO live outside the LLM boundary (e.g.
  a per-IP HTTP rate limit on `POST /v1/runs`) should get a new ADR
  number, not re-use 0005.
