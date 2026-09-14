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
>
> **Update 2026-09-13:** [PR #20](https://github.com/sh-ai-x/AgentOpsPipeline/pull/20)
> (rebuilt all three topologies on a real `langgraph.StateGraph`) and
> [PR #21](https://github.com/sh-ai-x/AgentOpsPipeline/pull/21) (wired real
> `search_docs`/`read_document` tool execution into `planner_executor`,
> fixed `api/server.py` to actually dispatch by `graph_version` instead of
> hardcoding `fixed`) removed the `planner_executor.py` half of the stub
> named below. `single_agent.py`'s tool-dispatch stub is untouched — that
> PR's scope was deliberately limited to `planner_executor`. Per-step
> verdicts below are updated accordingly; **the held-out re-run (step 7)
> has not happened yet**, so its numbers still reflect the pre-fix state.

## Per-step verdict

| Step | Phase | AC met? | One-line reason | Output |
|------|-------|---------|-----------------|--------|
| 1 | 0 · bootstrap | **yes** | scope + schema + 30 reviewed cases + 8 docs + 4 ADRs, all unit-tested | [`00-bootstrap/step1-output.json`](00-bootstrap/step1-output.json) |
| 2 | 1 · runnable-agent | **no** | "failed tool is visible" unimplemented (runs issue zero tool calls); refusal only vacuously tested; approval→publish flow not wired | [`01-runnable-agent/step2-output.json`](01-runnable-agent/step2-output.json) |
| 3 | 2 · mcp-integration | **no** (was fully unreachable; now partial) | `planner_executor` genuinely calls a `DocumentClient` for `search_docs`/`read_document` as of PR #21 — but it's still `InMemoryDocumentClient`, the in-process stand-in the code itself documents as "the real subprocess-based client is wired in step 6"; there is still no actual MCP stdio-protocol round trip and no stdio-subprocess integration test. Idempotent-ledger half is met | [`02-mcp-integration/step3-output.json`](02-mcp-integration/step3-output.json) |
| 4 | 3 · benchmark-prompts | **yes** | frozen held-out SHA (test-enforced), per-case reviewer/split, tuning on val only | [`03-benchmark-prompts/step4-output.json`](03-benchmark-prompts/step4-output.json) |
| 5 | 4 · topology-experiments | **no** (was both variants stubbed; now one of two) | `planner_executor`'s tool-dispatch stub is gone (PR #21); `graph/single_agent.py`'s is not — PR #20 only rebuilt its control flow onto `StateGraph`, deliberately preserving its stub behavior. The three-way comparison is no longer *all* tool-less, but no experiment has been re-run to produce new numbers, so ADR-0006's basis is still the old degenerate comparison | [`04-topology-experiments/step5-output.json`](04-topology-experiments/step5-output.json) |
| 6 | 5 · delivery | **no** (partially closed) | the "wire real MCP calls" work is now done for `planner_executor` (PR #21); still open for `single_agent`. Local gates re-run 2026-09-13 on `main`: `uv run pytest -q` → **177 passed, 0 failed** (the prior 1 failing test was a `.env`-dependent test-isolation artifact, not reproducing in this fresh worktree); "clean docker setup works" remains unverified | [`05-delivery/step6-output.json`](05-delivery/step6-output.json) |
| 7 | 6 · held-out-portfolio | **partial — unchanged** | reproducible (frozen SHA + manifest) ✓; `task_success` / `tool_correctness` numbers below are **pre-PR#20/#21** and have not been re-run since — this is the next concrete step, not yet done | [`06-held-out-portfolio/step7-output.json`](06-held-out-portfolio/step7-output.json) |

**2 of 7 acceptance criteria were cleanly met as of 2026-09-11 (steps 1, 4).**
As of 2026-09-13 (post PR #20/#21), steps 3/5/6 have moved from "stub, fully
unmet" to "real for `planner_executor`, still stubbed for `single_agent`,
not yet re-verified against their AC as written" — none has flipped to a
clean **yes** yet; step 2 (approval→publish flow, "failed tool is visible")
and step 7 (held-out re-run) are unchanged.

## Root cause tying steps 2/3/5/6/7 together

**Status 2026-09-13: half-closed.** The agent used to never issue tool
calls at all. `graph/fixed.py` still retrieves by reading `fixtures/docs/`
directly (by design — see README). `graph/single_agent.py:60` still carries
`# Tool dispatch is a stub for MVP; step 6 wires real MCP calls` — untouched.
`graph/planner_executor.py:72`'s equivalent stub is **gone**: PR #21 wired
real `search_docs`/`read_document` calls (against the in-process
`InMemoryDocumentClient`, not a real MCP subprocess yet) and normalizes
`get_issue` to `MCPError(kind="unsupported_capability")` — honestly, since
no real backend for `get_issue` exists anywhere in this codebase — rather
than faking a result. Remaining consequences:

- the MCP servers (step 3) are reachable from a `planner_executor` run now,
  but still via the in-process stand-in, not the real stdio subprocess;
- the topology comparison (step 5) is no longer *all* tool-less, but
  `single_agent` still is, and no comparison has been re-run;
- every held-out run (step 7) still reports the **pre-fix** `tool_correctness: 0.0`
  numbers below — re-running is the next step, not done yet;
- "failed tool is visible" (step 2) — `planner_executor`'s `tool_results`
  now surfaces a failure (e.g. `get_issue`'s `unsupported_capability`), but
  step 2's AC is scoped to the base runnable-agent phase, predates the
  topology variants, and the approval→publish flow it also names is still
  not wired regardless.

The document MCP server exposes **2** tools (`search_docs`, `read_document`).
`get_issue` is a prompt string only; `create_ticket_draft` / `publish_ticket`
are not tools — only `TicketLedger.publish()` exists, and `/v1/actions` mints a
nonce without ever calling it. `docs/EVIDENCE_CARD.md`'s "5 MVP tools" and
"144 tests" are both stale (2 real tools; the tree collects 154 tests).

## Deterministic gates — re-run 2026-09-13 (`main`, post PR #20/#21)

```
cd apps/agentops-workbench
uv run pytest -q      -> 177 collected, 177 passed, 0 failed
uv run ruff check .   -> 5 pre-existing errors, all in scripts/*.py (unrelated
                          screenshot helper; confirmed pre-dating #20/#21)
```

Previous run (2026-09-11, pre-fix): 154 collected, 153 passed, 1 failed. The
+23 tests are #20's structural `StateGraph` tests (10) and #21's tool-execution
tests (13). The one previously-failing test
(`test_has_insecure_jwt_secret_flags_default_and_short`) is not failing in
this fresh worktree — consistent with the original diagnosis that it's a
`.env`-presence artifact, not a real regression.

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

1. ~~Wire `graph/planner_executor.py` tool dispatch to a real MCP client~~ —
   **done, PR #21** (2026-09-13). `graph/single_agent.py`'s stub is still
   open — same fix, same shape, not yet done.
2. Add a stdio-subprocess integration test for the document server —
   **still open**. #21 wired `planner_executor` to `DocumentClient`, but the
   default implementation is still `InMemoryDocumentClient` (in-process
   stand-in), not the real stdio subprocess.
3. Connect run → ticket draft → `/v1/actions` approve → `TicketLedger.publish()`;
   add the "failed tool is visible" test — **still open**, untouched by #20/#21.
4. Fix the two vacuous tests above; fix the `.env`-sensitive auth test
   isolation — **still open** (not in #20/#21's scope; the auth test just
   happens not to be reproducing in a fresh worktree with no local `.env`).
5. Re-run the held-out experiment now that `planner_executor` has real
   tools — **still open, next concrete step**. `provider=local-fake` (CI
   default) can't produce a parseable plan for `planner_executor`, so this
   needs `provider=minimax` to actually move `tool_correctness`/`task_success`
   off 0.
6. ~~Refresh `docs/EVIDENCE_CARD.md` counts~~ — **done** (2026-09-13): 2 real
   tools (not 5), 177 tests (not 144).
