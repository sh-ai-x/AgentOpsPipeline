# Step 4 — 30-case dataset + scorers + prompt experiments

**Phase:** 3 (proposal §"Phase 3: Benchmark Curation and Prompt Experiments")
**Branch:** `feat/03-benchmark-prompts`
**Worktree:** `.worktrees/03-benchmark-prompts`
**Methodology:** TDD
**Estimated:** 1.0 week

## Work items

### 4.1 Curate 30 cases

- Add 18 cases to existing 12 pilot = 30 total.
- Final split: **18 dev / 6 val / 6 held-out**.
- Each case has: `id`, `family_id`, `task`, `expected_outcome`, `allowed_tools`, `source_refs`, `reviewer`, `split`.
- Held-out set is frozen (content hashed into `fixtures/cases/HELD_OUT_SHA256.txt`); changing a held-out case requires a new ADR.

### 4.2 Dataset card

- `fixtures/cases/DATASET_CARD.md`:
  - Family counts, reviewer per case, source-doc distribution.
  - Explicit "held-out not touched by tuning" attestation.
  - Acceptance / correction / duplicate rates from reviewer pass.

### 4.3 Node/task scorers

- `src/agentops_workbench/benchmark/scorers.py`:
  - `task_success(case, run_outcome)` — deterministic check against `expected_outcome`.
  - `retrieval_recall_at_k(case, evidence_ids, k)` — set overlap.
  - `tool_correctness(case, tool_calls)` — name in `allowed_tools` + canonical-args match.
  - `reliability(case, run_history)` — recovered vs duplicate-published vs timeout.
- `src/agentops_workbench/benchmark/judge.py` — optional LLM judge for groundedness on a human-reviewed subset; never grants permission or promotes labels.

### 4.4 Three-prompt comparison

- 3 prompt versions: `prompts/v1_baseline.md`, `v2_structured.md`, `v3_minimal.md`.
- Run all 3 against the **18 dev** cases with `provider=local-fake`.
- Pick the top-2 by validation (the 6 val cases); publish one unsuccessful change (v3_minimal underperformed; keep the change visible).

## TDD plan

1. **Red** `tests/test_scorers.py` — golden inputs for each scorer; assert metric values.
2. **Red** `tests/test_held_out_frozen.py` — assert `HELD_OUT_SHA256.txt` matches the on-disk held-out cases.
3. **Red** `tests/test_judge_isolation.py` — judge failures never flip a deterministic scorer result.
4. **Red** `tests/test_dataset_card.py` — every case has a non-empty `reviewer`; split counts match `18/6/6`.

## Exit criteria

- 30 cases reviewed and split.
- Scorers green; judge isolated.
- Three-prompt report published; v3_minimal's failure explained.
- Held-out set untouched by prompt selection.

## Risks

- Held-out contamination: scorer development must NEVER touch held-out cases; enforced by test.
- LLM judge drift: only run on a fixed subset, never promote labels.
