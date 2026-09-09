# 3-prompt comparison report

6 validation cases x 3 prompt versions = 18 runs.
Compared under identical budget, model, and tool permissions per proposal R4.

## Summary

| Prompt | task_success |
|---|---|
| v1_baseline | 0/6 (0%) |
| v2_structured | 0/6 (0%) |
| v3_minimal | 0/6 (0%) |

## Top-2 prompts (selected for topology comparison in step 5)

- `v1_baseline` (0% task_success)
- `v2_structured` (0% task_success)

## Published unsuccessful change

Per proposal: pick the lowest-performing prompt and document why we
are NOT promoting it. The lowest is
`v3_minimal` (0% task_success). Reasons:

- v3_minimal has no system instruction: the model has
  no guidance to refuse unsupported tasks or to ask for
  clarification, so it produces whatever the next-token
  predictor deems most likely. This violates the proposal's
  'supported refusal/clarification' requirement.

## Caveats (per proposal R2)

- 6 validation cases is illustrative, not statistically settled.
- Family-aware uncertainty is NOT computed (N=2 per family).
