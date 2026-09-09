# Step 1 — Repo bootstrap, ADRs, scope fixtures, pilot dataset

**Phase:** 0 (proposal §"Phase 0: Scope and Ground Truth")
**Branch:** `feat/00-bootstrap`
**Worktree:** `.worktrees/00-bootstrap` (cut off `origin/main` of `~/dev/agentops-workbench`)
**Methodology:** TDD
**Estimated:** 0.5 week

## Pre-step setup

1. Create `~/dev/agentops-workbench` from a minimal `uv` scaffold.
2. `git init`, push to a private remote.
3. Cut worktree `.worktrees/00-bootstrap` on branch `feat/00-bootstrap`.

## Work items

### 1.1 Repo scaffold (no production code yet)

- `pyproject.toml` pinning Python `>=3.10`, `uv` lockfile, dev-deps: `pytest`, `ruff`, `pytest-asyncio`.
- `src/agentops_workbench/` empty package.
- `tests/` empty.
- `docker/docker-compose.yml` placeholder.
- `.github/workflows/ci.yml` running `uv run ruff check && uv run pytest`.
- `.gitignore`, `README.md`, `LICENSE` (MIT or Apache-2.0).

### 1.2 Scope doc

- `docs/scope.md` — one paragraph user workflow; explicit permissions; explicit exclusions.
- Confirm against PRD §"Scope (in / out)"; flag any deltas.

### 1.3 Fixture schema + 12 pilot cases

- `fixtures/cases/schema.json` — Pydantic model dumped as JSON Schema.
- `fixtures/cases/pilot/*.json` — 12 cases, 2 per family (straightforward, multi-doc, ambiguous, missing evidence, stale doc, tool failure).
- `fixtures/docs/` — 8 short synthetic docs (CC-BY-SA or Apache-2.0 attribution per source).
- Each pilot case has: `id`, `family_id`, `task`, `expected_outcome`, `allowed_tools`, `source_refs`, `reviewer`, `split` ∈ `{`dev`}` (no val/held-out yet).

### 1.4 Four ADRs

- `docs/adr/0001-langgraph.md` — why LangGraph; alternatives considered; rejection rationale.
- `docs/adr/0002-mcp-boundaries.md` — stdio only for MVP; Streamable HTTP deferred; one pinned external server.
- `docs/adr/0003-provider-abstraction.md` — `LLMAdapter` interface; `provider=minimax` default live; `provider=local-fake` CI.
- `docs/adr/0004-dataset-separation.md` — dev/val/held-out splits frozen before Phase 3; reviewer required per case.

## TDD plan (red → green → refactor)

1. **Red:** `tests/test_fixture_schema.py` — load each pilot JSON; assert schema match; assert `split == 'dev'` for all 12.
2. **Green:** write `fixtures/cases/schema.json` + 12 pilot files.
3. **Refactor:** extract a `load_case(path)` helper in `src/agentops_workbench/benchmark/load.py`.

A second red→green cycle for the ADR existence test: `tests/test_adrs_present.py` asserts all 4 ADRs exist and contain `## Decision` + `## Consequences` headings.

## Exit criteria

- `uv run pytest` green with the new regression tests.
- `uv run ruff check` clean.
- A second developer can read `docs/scope.md` + `fixtures/cases/pilot/01.json` and answer "what does good look like?" without asking.
- PR opened, CI green, merged.

## Risks

- Drift between the proposal's Phase 0 list and this step list. Resolve by re-reading proposal §"Phase 0" before merging.
