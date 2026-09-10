# Build report — AgentOps Workbench (Phases 0–6)

> **Audit, not a build log.** `/dev-kit:build` was never run in this monorepo —
> the workbench was built standalone and imported via PR #8, so the per-step
> `step<N>-output.json` files the runner emits never existed. This report and the
> seven `phases/<NN-slug>/step<N>-output.json` files audit the **merged tree**
> under `apps/agentops-workbench/` against each step's acceptance criterion, plus
> a re-run of the deterministic gates on **2026-09-11**.
>
> The first pass of these files marked every step `completed` / `acceptance_met:
> true`. That was wrong. Corrected verdicts below.

## Per-step verdict

| Step | Phase | AC met? | One-line reason | Output |
|------|-------|---------|-----------------|--------|
| 1 | 0 · bootstrap | **yes** | scope + schema + 30 reviewed cases + 8 docs + 4 ADRs, all unit-tested | [`00-bootstrap/step1-output.json`](00-bootstrap/step1-output.json) |
| 2 | 1 · runnable-agent | **no** | "failed tool is visible" unimplemented (runs issue zero tool calls); refusal only vacuously tested; approval→publish flow not wired | [`01-runnable-agent/step2-output.json`](01-runnable-agent/step2-output.json) |
| 3 | 2 · mcp-integration | **no** | 2 tools (not 5), tested in-process only; no run invokes the MCP server; no stdio-subprocess integration test. Idempotent-ledger half is met | [`02-mcp-integration/step3-output.json`](02-mcp-integration/step3-output.json) |
| 4 | 3 · benchmark-prompts | **yes** | frozen held-out SHA (test-enforced), per-case reviewer/split, tuning on val only | [`03-benchmark-prompts/step4-output.json`](03-benchmark-prompts/step4-output.json) |
| 5 | 4 · topology-experiments | **no** | tool dispatch is `# stub for MVP` in both variants; `tool_correctness` 0/24; the comparison behind ADR-0006 is degenerate | [`04-topology-experiments/step5-output.json`](04-topology-experiments/step5-output.json) |
| 6 | 5 · delivery | **no** | the "wire real MCP calls" work step 5 deferred here was never done; 1 regression test fails in the dev env; "clean docker setup works" is unverified | [`05-delivery/step6-output.json`](05-delivery/step6-output.json) |
| 7 | 6 · held-out-portfolio | **partial** | reproducible (frozen SHA + manifest) ✓; but `task_success` / `tool_correctness` are 0/24, so the shipping-decision basis is thin; freeze tag + demo recording missing | [`06-held-out-portfolio/step7-output.json`](06-held-out-portfolio/step7-output.json) |

**2 of 7 acceptance criteria are cleanly met (steps 1, 4).** Steps 2, 3, 5, 6
have a real, shipped surface but do not satisfy their AC as written; step 7 is
reproducible but rests on zero primary-metric signal.

## Root cause tying steps 2/3/5/6/7 together

The agent never issues tool calls. `graph/fixed.py` retrieves by reading
`fixtures/docs/` directly; `graph/single_agent.py:60` and
`graph/planner_executor.py:72` both carry `# Tool dispatch is a stub for MVP;
step 6 wires real MCP calls`. Step 6 did not do that wiring. Consequences:

- the MCP servers (step 3) are built and unit-tested but unreachable from a run;
- the topology comparison (step 5) compares three tool-less answer generators;
- every held-out run (step 7) reports `tool_correctness: 0.0`;
- "failed tool is visible" (step 2) has no surface to be visible on.

The document MCP server exposes **2** tools (`search_docs`, `read_document`).
`get_issue` is a prompt string only; `create_ticket_draft` / `publish_ticket`
are not tools — only `TicketLedger.publish()` exists, and `/v1/actions` mints a
nonce without ever calling it. `docs/EVIDENCE_CARD.md`'s "5 MVP tools" and
"144 tests" are both stale (2 real tools; the tree collects 154 tests).

## Deterministic gates — re-run 2026-09-11

```
cd apps/agentops-workbench
uv run pytest -q      -> 154 collected, 153 passed, 1 failed
uv run ruff check .   -> All checks passed
```

Test count by file (154):

| File | Tests | | File | Tests |
|------|-------|-|------|-------|
| `test_fixture_schema.py` | 33 | | `test_auth_hardening.py` | 10 |
| `mcp/test_document_server.py` | 22 | | `test_held_out.py` | 8 |
| `benchmark/test_scorers.py` | 16 | | `test_adrs_present.py` | 8 |
| `test_observability.py` | 15 | | `llm/test_factory.py` | 4 |
| `test_api_runs.py` | 15 | | `llm/test_local_fake_adapter.py` | 3 |
| `graph/test_topology.py` | 11 | | `experiments/test_prompts.py` | 3 |
| `worker/test_runner.py` | 2 | | `test_smoke.py` | 2 |
| `test_alembic.py` | 2 | | | |

### The one failing test

`tests/test_auth_hardening.py::test_has_insecure_jwt_secret_flags_default_and_short`
— asserts the default JWT secret is flagged insecure, but `Settings`
(pydantic-settings) reads `apps/agentops-workbench/.env`, which sets a strong
`AGENTOPS_JWT_SECRET`, so the check returns `False`. **Test-isolation defect, not
a production bug**; passes in CI where no `.env` exists. Fix: build the `Settings`
under test with `_env_file=None` or monkeypatch the source.

### Weak / vacuous tests found during the audit

- `graph/test_topology.py`-adjacent `test_fixed_graph_refuses_when_classifier_returns_refuse`
  asserts nothing unless `route == "refuse"` (the comment says it forces REFUSE; the code does not).
- `test_api_runs.py::test_run_reaches_terminal_state` accepts `state == FAILED`,
  so it does not prove a normal task answers.

## Live experiments (frozen, `provider=minimax` / `MiniMax-M3`)

| Experiment | Runs | Tokens | Cost | task_success | tool_correctness |
|------------|------|--------|------|--------------|------------------|
| Held-out (`experiments/held-out-v1/`) | 24 | 9,074 | $0.0124 | 0/24 | 0/24 |
| 3-prompt (`experiments/prompts-v1/`) | 18 | 14,597 | ~$0.02 | 0/18 | — |

`retrieval_recall` on the held-out set: 1.0 on 20/24 runs, 0.5 on 4/24. The
agent finds the right documents and never acts on them.

## What would close the gaps

1. Wire `graph/single_agent.py` + `graph/planner_executor.py` tool dispatch to a
   real MCP client (removes both `# stub for MVP` comments).
2. Add a stdio-subprocess integration test for the document server.
3. Connect run → ticket draft → `/v1/actions` approve → `TicketLedger.publish()`;
   add the "failed tool is visible" test.
4. Fix the two vacuous tests above; fix the `.env`-sensitive auth test isolation.
5. Re-run the held-out experiment once tools work; cut `experiment-v1-frozen`.
6. Refresh `docs/EVIDENCE_CARD.md` counts (2 tools, 154 tests).
