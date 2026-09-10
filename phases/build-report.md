# Build report — AgentOps Workbench (Phases 0–6)

> Reconstructed build record. The `/dev-kit:build` runner was **never executed
> in this monorepo** — the workbench was built in a standalone repo and imported
> via PR #8, so the per-step `step<N>-output.json` files the runner would have
> emitted never existed. This report and the seven
> `phases/<NN-slug>/step<N>-output.json` files are reconstructed from the shipped
> artefacts under `apps/agentops-workbench/` plus a re-run of the deterministic
> gates on **2026-09-11**.
>
> `exit_code: 0` / `acceptance_met` in each JSON is a judgement against the
> shipped tree, not a recorded process exit.

## Per-step summary

| Step | Phase | Output file | AC met | Key artefacts |
|------|-------|-------------|--------|---------------|
| 1 | 0 · 00-bootstrap | [`00-bootstrap/step1-output.json`](00-bootstrap/step1-output.json) | yes | `pyproject.toml` + lock, `docs/scope.md`, `fixtures/cases/schema.json`, 30 pilot cases, 8 docs, ADR 0001–0004 |
| 2 | 1 · 01-runnable-agent | [`01-runnable-agent/step2-output.json`](01-runnable-agent/step2-output.json) | yes | `llm/`, `graph/{fixed,state}.py`, `api/server.py`, `mocks/tickets.py`, `worker/runner.py`, `streamlit_app/app.py` |
| 3 | 2 · 02-mcp-integration | [`02-mcp-integration/step3-output.json`](02-mcp-integration/step3-output.json) | yes | `mcp/mcp_servers/document/server.py`, `mcp/mcp_servers/filesystem/scope_guard.py` |
| 4 | 3 · 03-benchmark-prompts | [`03-benchmark-prompts/step4-output.json`](03-benchmark-prompts/step4-output.json) | yes | `fixtures/cases/{dev,val,held_out}/`, `HELD_OUT_SHA256.txt`, `benchmark/{scorers,load}.py`, `experiments/prompts-v1/` |
| 5 | 4 · 04-topology-experiments | [`04-topology-experiments/step5-output.json`](04-topology-experiments/step5-output.json) | yes | `graph/{single_agent,planner_executor,topology}.py`, `docs/adr/0006-topology.md` |
| 6 | 5 · 05-delivery | [`05-delivery/step6-output.json`](05-delivery/step6-output.json) | yes | `observability/otel.py`, `alembic/versions/0001_initial.py`, `docker/`, `docs/RUNBOOK.md`, `tests/test_auth_hardening.py` |
| 7 | 6 · 06-held-out-portfolio | [`06-held-out-portfolio/step7-output.json`](06-held-out-portfolio/step7-output.json) | yes | `experiments/held-out-v1/`, `docs/EVIDENCE_CARD.md`, `docs/demo.md` |

## Deterministic gates — re-run 2026-09-11

```
cd apps/agentops-workbench
uv run pytest -q      -> 154 collected, 153 passed, 1 failed
uv run ruff check .   -> All checks passed
```

Test count by file (154 total):

| File | Tests |
|------|-------|
| `tests/test_fixture_schema.py` | 33 |
| `tests/mcp/test_document_server.py` | 22 |
| `tests/benchmark/test_scorers.py` | 16 |
| `tests/test_observability.py` | 15 |
| `tests/test_api_runs.py` | 15 |
| `tests/graph/test_topology.py` | 11 |
| `tests/test_auth_hardening.py` | 10 |
| `tests/test_held_out.py` | 8 |
| `tests/test_adrs_present.py` | 8 |
| `tests/llm/test_factory.py` | 4 |
| `tests/llm/test_local_fake_adapter.py` | 3 |
| `tests/experiments/test_prompts.py` | 3 |
| `tests/worker/test_runner.py` | 2 |
| `tests/test_smoke.py` | 2 |
| `tests/test_alembic.py` | 2 |

(The app `README.md` still tags "137 tests"; `docs/EVIDENCE_CARD.md` says "144";
the current tree collects 154.)

### The one failing test

`tests/test_auth_hardening.py::test_has_insecure_jwt_secret_flags_default_and_short`

- **Cause:** the test asserts `Settings(provider="local-fake").has_insecure_jwt_secret() is True`
  (the default secret `dev-only-please-rotate` must be flagged). `Settings` is a
  `pydantic-settings` model that reads `apps/agentops-workbench/.env`; that local
  file sets a strong `AGENTOPS_JWT_SECRET`, so the check returns `False` and the
  assertion fails. The test does not isolate the `.env` source.
- **Scope:** test-isolation defect, **not** a production-code bug. It passes in CI,
  where no `.env` file is present.
- **Suggested fix:** construct the `Settings` under test with `_env_file=None`, or
  `monkeypatch` the settings source, so the assertion is independent of the
  developer's local `.env`.

## Live experiments (frozen, `provider=minimax` / `MiniMax-M3`)

| Experiment | Runs | Tokens | Cost | Notes |
|------------|------|--------|------|-------|
| Held-out (`experiments/held-out-v1/`) | 24 (6 cases × 2 topologies × 2 trials) | 9,074 (5,782 prompt + 3,292 completion) | $0.0124 | `prompt_version=v1_baseline`; `code_sha=a5b489b`; held-out SHA `d3bef8c3…d8d0a5` |
| 3-prompt comparison (`experiments/prompts-v1/`) | 18 (6 val cases × 3 versions) | 14,597 | ~$0.02 | `v1_baseline` + `v2_structured` advance; `v3_minimal` published as the unsuccessful change |

**Measured task_success is 0%** on every held-out and prompt run. Per
`docs/EVIDENCE_CARD.md` this is the conservative substring-match scorer scoring
semantically-correct answers as false — a documented limitation, not a
regression. The shipping decision (fixed graph as default) rests on token
efficiency (`single_agent` burned 2–10× the completion tokens of `fixed`) and
`retrieval_recall` (1.0 on 5/6 held-out families), not on an end-to-end success
rate.

## Open items (carried from the shipped docs)

- `experiment-v1-frozen` git tag was never cut.
- `docs/demo.md` is a 5-minute script, not a recording.
- `single_agent` / `planner_executor` TOOL branches are tool-less (only `fixed` wires MCP tools end to end).
- Fix the `.env`-sensitive auth-hardening test isolation (above).
