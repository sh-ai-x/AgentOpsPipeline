# Held-out uncertainty

- Held-out SHA: `d3bef8c35a3bf9de539ab67a988e83a2d5434746bc8c6001f85ddf569dc8d0a5` (frozen; do not edit)
- Code SHA: `a5b489b`
- Provider: `minimax`
- Total runs: 24

## Per-topology summary

- **fixed**: 0/12 task_success (0%)
- **single_agent**: 0/12 task_success (0%)

## Caveats

- 6 held-out cases x 2 trials x 2 topologies = 24 runs is illustrative, not statistically settled.
- Family-aware uncertainty is NOT computed because sample size per family is too small (1 case / family).
- Temperature 0 is set; provider-side stochasticity may still cause non-determinism.
