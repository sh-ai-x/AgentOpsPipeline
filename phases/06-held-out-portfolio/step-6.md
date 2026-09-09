# Step 7 — Held-out evaluation + evidence card + demo

**Phase:** 6 (proposal §"Phase 6: Held-Out Evaluation and Portfolio")
**Branch:** `feat/06-held-out-portfolio`
**Worktree:** `.worktrees/06-held-out-portfolio`
**Methodology:** TDD
**Estimated:** 1.0 week

## Work items

### 7.1 Freeze configurations

- Tag `git tag experiment-v1-frozen` after Step 6 merge.
- Lock `model_config`, `prompt_version`, tool permissions, budget.

### 7.2 Run the budgeted held-out experiment

- 6 held-out cases × 2 selected topologies × 2 trials = 24 runs.
- `provider=minimax` live (or `provider=local-fake` for the dry-run).
- `SpendCeiling` enforced before execution; shrink the sample + state the limitation if budget insufficient.

### 7.3 Publish outcomes

- `experiments/held-out-v1/outcomes.jsonl` — raw per-run outcomes.
- `experiments/held-out-v1/manifest.json` — exact versions of every dependency + the code SHA.
- `experiments/held-out-v1/failed_cases.md` — the failed runs and why.
- `experiments/held-out-v1/uncertainty.md` — family-aware uncertainty statements.

### 7.4 Five-minute demo recording

- `docs/demo.md` — 5-minute script: submit task → MCP calls → result → topology comparison → seeded regression fail.

### 7.5 Evidence card

- `docs/EVIDENCE_CARD.md` — single page with personal contributions + measured results only (no claims before measurement).

## TDD plan

1. **Red** `tests/test_held_out_uncontaminated.py` — held-out set SHA matches `HELD_OUT_SHA256.txt`; tuning configs never reference held-out cases.
2. **Red** `tests/test_outcomes_schema.py` — every line of `outcomes.jsonl` has `run_id`, `case_id`, `topology`, `trial`, `metrics`, `tokens`, `cost_usd`.
3. **Red** `tests/test_spend_ceiling.py` — execution aborts if projected cost > `SpendCeiling`.

## Exit criteria

- 24 runs (or fewer, with limitation) logged under `experiments/held-out-v1/`.
- A reviewer can clone the repo, run `make reproduce-held-out`, and see the same raw counts.
- EVIDENCE_CARD.md cites only published numbers; resumé template placeholders are filled.

## Risks

- Held-out contamination (R2): assert by SHA + by tuning-config audit.
- Cost overrun: `SpendCeiling` test fails before any live run starts.
