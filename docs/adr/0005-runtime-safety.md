# ADR-0005: Runtime safety / cost cap (tombstone — absorbed into ADR-0003)

## Status

**Tombstone (2026-09-09).** The "runtime safety / cost cap" decision this
number was reserved for was folded into
[ADR-0003 Provider abstraction](../../apps/agentops-workbench/docs/adr/0003-provider-abstraction.md)
(see its "cost cap" section). The number is preserved to keep the surrounding
ADRs stable and to make the "where did 0005 go?" question self-answering.

If a new runtime-safety decision needs a number, allocate the next free
integer (0007+). Do not backfill this slot.

## Context

During the original 7-step plan (`.dev-kit/round-1/phases/build/step1.md`
§1.4; `step3.md` §3.2 also references an "ADR-0005 amendment" for the
filesystem MCP pin), ADR-0005 was reserved for "how do we stop a runaway
agent from racking up unbounded LLM spend?" — the cap that became the
`LLMAdapter` per-call cost limit plus the cumulative-spend check in the
adapter chat path.

## Decision

**Absorbed into ADR-0003.** The cost cap is a property of the provider
abstraction, not a separate cross-cutting control:

- The cap has no consumers outside the LLM boundary (no HTTP rate limiter,
  no per-token budget in the MCP layer). Co-locating it with the resource
  it gates keeps the control surface small.
- A separate "safety" ADR would have described a single guard in a single
  class; the value-per-document ratio did not justify the file.

The `step3.md` "ADR-0005 amendment" for the filesystem-server version pin is
likewise covered: the pin is recorded in `pyproject.toml` and documented in
ADR-0002 (MCP boundaries).

## Consequences

- ADR-0003 is the single source of truth for both provider selection and
  spend control.
- Cross-references in `apps/agentops-workbench/docs/adr/` point at ADR-0003
  for spend control, not at this tombstone.
- Future safety controls that DO live outside the LLM boundary (e.g. a
  per-IP HTTP rate limit on `POST /v1/runs`) should get a new ADR number,
  not reuse 0005.
