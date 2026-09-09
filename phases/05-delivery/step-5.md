# Step 6 — OTel, regression, Docker Compose, runbook

**Phase:** 5 (proposal §"Phase 5: Failure Evidence and Delivery")
**Branch:** `feat/05-delivery`
**Worktree:** `.worktrees/05-delivery`
**Methodology:** TDD
**Estimated:** 1.5 weeks

## Work items

### 6.1 OpenTelemetry exporter

- `src/agentops_workbench/observability/otel.py` — span around model calls, tool calls, state transitions, failures.
- Redaction: strip `api_key`, `authorization`, `bearer`, `password` substrings and known credential fields before exporting.

### 6.2 Failure-to-regression

- Pick one failed case from Step 5; capture the trace; write the smallest possible test that fails because of the bug; fix it; verify the test now passes.

### 6.3 Recovery, scope isolation, approval replay tests

- Already covered in Steps 2 and 3; re-run all of them in the offline CI matrix.
- Add an explicit "approval replay with mutated args" test (must reject).

### 6.4 Docker Compose + Alembic

- `docker/docker-compose.yml`: `postgres`, `api`, `worker`, `streamlit`, `mcp-document`, `mcp-filesystem` (pinned).
- `alembic upgrade head` runs as part of `api` startup.
- `docker compose up --exit-code-from app` is the offline-CI smoke.

### 6.5 Offline CI + runbook

- `.github/workflows/ci.yml`: ruff, pytest, docker compose smoke.
- `docs/RUNBOOK.md`: how to bring the stack up, how to clear the mock ledger, how to read a trace, how to re-run a held-out case.

## TDD plan

1. **Red** `tests/test_otel_redaction.py` — synthetic secret in a trace is replaced with `[REDACTED]`.
2. **Red** `tests/test_failure_to_regression.py` — seed the captured failure; assert it fails pre-fix and passes post-fix.
3. **Red** `tests/test_approval_replay_with_mutated_args.py` — mutated args after approval → 403.
4. **Red** `tests/test_offline_ci_smoke.py` — `docker compose -f docker/docker-compose.yml up` exits 0 on a 1-task smoke.

## Exit criteria

- OTel trace for any held-out run ties every tool call back to the BenchmarkCase.
- One published failed case → regression test that fails without the fix.
- A clean checkout + `docker compose up` + the 1-task smoke exits 0.
- RUNbook read by a teammate who has never seen the repo can bring up the stack.

## Risks

- Credentials leaking via trace payloads (R-secrets): redaction test must cover JSON nested fields, header arrays, and message content.
