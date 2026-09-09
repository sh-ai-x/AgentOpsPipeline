# ADR-0004: Dataset separation (dev / val / held-out)

## Status

Accepted (2026-09-08).

## Decision

- 30 cases split **18 dev / 6 val / 6 held-out**, grouped by family
  and source-document.
- Each case carries: `id`, `family_id`, `task`, `expected_outcome`,
  `allowed_tools`, `source_refs`, `reviewer`, `split`.
- Held-out set is frozen: content hashed into
  `fixtures/cases/HELD_OUT_SHA256.txt`. Changing a held-out case
  requires a new ADR.
- Tuning happens only on dev + val. Held-out is read at the final
  evaluation step in Phase 6.

## Consequences

- Held-out set is small (6 cases) by design — proposal explicitly
  labels this "illustrative, not statistically settled."
- Reviewer + split are first-class fields. A test enforces
  `reviewer != ""` and split counts (18/6/6).
- A synthetic candidate generator pipeline is **deferred** to a later
  phase (out of MVP).
