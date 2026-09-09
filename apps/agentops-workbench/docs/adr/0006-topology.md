# ADR-0006: Topology shipping choice

## Status

Accepted (2026-09-08).

## Decision

Ship the **fixed graph** as the default topology for the held-out
evaluation (Phase 6 / Step 7). The single-agent and planner/executor
variants remain available for per-experiment comparison.

## Rationale

- All three topologies share the outer `MAX_STEPS=8` budget cap (R4
  invariant), so the comparison is interpretable as "which topology
  reaches the same outcome under the same constraints?"
- On the matched-budget comparison, the fixed graph:
  - Reaches a terminal state for every task in the dev + val split.
  - Uses the smallest step count on average (1-2 LLM calls per run vs
    3-5 for the planner/executor and 2-6 for the single-agent).
  - Has the lowest token usage under identical budgets.
- The planner/executor variant occasionally produces more detailed
  answers for multi-document queries, but the additional cost does not
  justify the shipping configuration under the proposal's "a simpler
  workflow may win" caveat.

## Limitations (per proposal §"Step-by-Step Build Guide" / Phase 4)

- Staged selection: prompt family and topology were NOT jointly
  optimized. A full factorial search is optional and deferred.
- Held-out set is 6 cases (small by design; proposal explicitly labels
  this "illustrative, not statistically settled").
- Topology comparison does not vary temperature / model / corpus; any
  drift between runs invalidates the comparison.

## Consequences

- Default `graph_version="fixed-v1"` in `CreateRunBody`.
- Single-agent and planner/executor remain selectable via the topology
  registry for future experiments.
- Topology comparison report published under `experiments/topology-v1/`.
