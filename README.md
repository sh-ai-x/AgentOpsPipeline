# AgentOps Workbench

A support-operations agent that turns a repository issue into a *grounded*
answer and an *approval-gated* ticket draft, plus an experiment workbench that
compares prompt, workflow-topology and tool-integration choices on a frozen
30-case benchmark.

The contribution is one complete application and one measurement study — not a
general-purpose agent framework. LangGraph from the first release, LangChain
integrations, an MCP document server and a pinned filesystem server.

- **Scope of record:** [`docs/proposals/agentops-workbench-proposal.md`](docs/proposals/agentops-workbench-proposal.md)
- **Application:** [`apps/agentops-workbench/`](apps/agentops-workbench/) — `src/`, `fixtures/`, `experiments/`, `docker/`, 154 tests (imported in PR #8)
- **Phase index + build audit:** [`phases/index.md`](phases/index.md), [`phases/build-report.md`](phases/build-report.md)
- **ADR catalogue:** [`docs/adr/README.md`](docs/adr/README.md)

---

## Progress

### Build phases

| Phase | Scope | Acceptance criterion met? |
|---|---|---|
| 0 — Scope & ground truth | scope doc, typed contracts, 4 ADRs, 30 reviewed cases, 8 docs | ✅ **yes** — schema + ADR + fixture tests all pass |
| 1 — Runnable agent & API | fixed LangGraph graph, FastAPI + JWT, fake + live adapters, mock ledger, Streamlit | ❌ **no** — answer/refuse path works, but the run issues no tool calls, so "failed tool is visible" is unimplemented and run → draft → approve → publish is not connected |
| 2 — MCP & reliable tool use | document MCP server, pinned filesystem server, error envelopes, scope guard, duplicate-delivery test | ❌ **no** — 2 tools, tested in-process only; no agent run invokes the server. The idempotent-ledger half of the AC is met |
| 3 — Benchmark curation & prompt experiments | 30 cases 18/6/6, frozen held-out hash, node/task scorers, 3-prompt comparison | ✅ **yes** — held-out SHA is test-enforced, every case has a reviewer, tuning ran on validation only |
| 4 — Topology & planning experiments | single-agent + planner/executor variants, matched-budget comparison, shipping choice | ❌ **no** — tool dispatch is `# stub for MVP` in both variants; the comparison behind ADR-0006 is between three tool-less answer generators |
| 5 — Failure evidence & delivery | redacted OTel export, seeded regression, Docker Compose, Alembic, offline CI | ❌ **no** — OTel/redaction/compose/migrations/runbook shipped and the redaction path is tested, but the MCP wiring this phase owned was never done and one regression test fails in the dev env |
| 6 — Held-out evaluation & portfolio | budgeted held-out run, raw outcomes + uncertainty, evidence card, demo | 🟡 **partial** — the run is reproducible from a frozen SHA + manifest, but `task_success` and `tool_correctness` are both 0/24, the `experiment-v1-frozen` tag was never cut, and the demo is a script not a recording |

Full evidence per phase: [`phases/build-report.md`](phases/build-report.md) and
`phases/<NN-slug>/step<N>-output.json`.

### Design decisions

| ADR | Decision |
|---|---|
| 0001 | LangGraph (`langgraph==1.2.11`) as the workflow engine |
| 0002 | MCP boundaries — custom document server + pinned `@modelcontextprotocol/server-filesystem`, stdio, spec `2026-07-28`, fixture-only scope |
| 0003 | Provider abstraction — single `LLMAdapter`; `minimax` live / `local-fake` CI; no provider name in graph code; per-call + cumulative cost cap |
| 0004 | Dataset separation — 30 cases 18 dev / 6 val / 6 held-out; held-out content-hashed and frozen before Phase 3 |
| 0005 | *tombstone* — runtime-safety / cost-cap decision folded into ADR-0003 ([`docs/adr/0005-runtime-safety.md`](docs/adr/0005-runtime-safety.md)) |
| 0006 | Ship the fixed graph as the default topology |

### The central gap

**No agent run issues a tool call.** `graph/fixed.py` retrieves by reading
`fixtures/docs/` directly; `graph/single_agent.py` and
`graph/planner_executor.py` both carry `# Tool dispatch is a stub for MVP; step
6 wires real MCP calls`, and step 6 never did that wiring. So:

- the MCP servers are built and unit-tested but unreachable from a run;
- the topology comparison compares tool-less generators;
- every held-out run reports `task_success` and `tool_correctness` of 0;
- `docs/EVIDENCE_CARD.md` overstates the tool count (5 claimed, 2 real) and the
  test count (144 claimed, 154 collected).

Retrieval works — `retrieval_recall` is 1.0 on 20 of 24 held-out runs. The agent
finds the right documents and never acts on them.

---

## Usage

```bash
cd apps/agentops-workbench
uv sync --extra dev
cp .env.example .env          # AGENTOPS_MINIMAX_API_KEY for live experiments; CI needs none

uv run pytest -q                                              # 153 pass, 1 env-only failure (see below)
uv run ruff check .                                           # clean
uv run uvicorn agentops_workbench.api.server:app --port 8000  # REST API
uv run streamlit run streamlit_app/app.py                     # submit / inspect / approve UI
docker compose -f docker/docker-compose.yml up                # postgres + api + worker + streamlit + mcp-document
```

> `tests/test_auth_hardening.py::test_has_insecure_jwt_secret_flags_default_and_short`
> fails locally when `apps/agentops-workbench/.env` exists (it sets a strong
> `AGENTOPS_JWT_SECRET` and the test does not isolate the env-file source). It
> passes in CI. Test-isolation defect, not a production bug.

REST surface (HS256 JWT):

```
POST /v1/runs                 # submit an issue -> queued run
GET  /v1/runs/{id}            # state + answer + trace_id
POST /v1/runs/{id}/cancel     # stop future work
POST /v1/actions              # mint an approval nonce (not yet wired to publish_ticket)
```

Experiments (frozen; re-run needs `provider=minimax`):

```bash
uv run python -m agentops_workbench.experiments.prompts        # 3 prompts x 6 val cases
AGENTOPS_PROVIDER=minimax \
  uv run python -m agentops_workbench.experiments.run_held_out # 6 cases x 2 trials x 2 topologies
# SpendCeiling (default $5.00) is enforced before any live call.
```

---

## Optimization study — PROBLEM · ANALYSIS · [ ADVANCE → METRIC : SUPPOSE — RESULT ] · SOLUTION

### PROBLEM

Given a repository issue, produce a grounded answer and an approval-gated ticket
draft — refusing or asking for clarification when the evidence does not support
an answer — and decide, with evidence, which prompt and which workflow topology
to ship.

### ANALYSIS

- **Correctness is multi-axis.** A run can retrieve the right documents and still
  call the wrong tool; it can answer fluently with no grounding. The scorecard
  separates `task_success`, `retrieval_recall@k`, `tool_correctness`,
  reliability, and cost/latency.
- **Topology comparison is only meaningful under a matched budget.** Fixed graph,
  single agent, and planner/executor must share the corpus, prompt family, model,
  tool permissions, and the outer `MAX_STEPS` cap (R4).
- **The held-out set is tiny by design (6 cases)** — "illustrative, not
  statistically settled."
- **The model chooses nothing that matters.** Identity comes from the JWT
  principal; approval binds user + run + tool + canonical args + nonce;
  `publish_ticket` is idempotent on a stable action key.

### [ ADVANCE → METRIC : SUPPOSE — RESULT ]

**Advance 1 — Prompt family, under a fixed graph.** `experiments/prompts-v1/` ·
3 prompts × 6 validation cases = 18 runs, matched budget.

- **→ METRIC:** `task_success`, prompt/completion tokens, latency.
- **: SUPPOSE:** `v2_structured` beats `v1_baseline`; `v3_minimal` is worst.
- **— RESULT:** 0/6 · 0/6 · 0/6. Ordering was untestable — every prompt scored
  zero because tool execution downstream of the prompt is stubbed. `v3_minimal`
  was still published as the documented unsuccessful change (no system
  instruction ⇒ cannot satisfy the "supported refusal / clarification"
  requirement regardless).

**Advance 2 — Topology, on the frozen held-out set.**
`experiments/held-out-v1/` · fixed vs. single_agent · 24 runs · `provider=minimax`,
`MiniMax-M3`, `v1_baseline`, ceiling $5.00.

- **→ METRIC:** `task_success`, `retrieval_recall`, `tool_correctness`,
  `cost_usd`, `duration_ms`, per family.
- **: SUPPOSE:** the fixed graph reaches the same outcomes at lower cost.
- **— RESULT:** `fixed` 0/12 · `single_agent` 0/12 `task_success`;
  `tool_correctness` 0.0 on all 24. `retrieval_recall` 1.0 on 20/24 — the
  sub-metrics localise the fault to tool execution. `single_agent` spent 2–10×
  the completion tokens for no gain (this *does* support "a simpler workflow may
  win"). Live cost $0.0124 for the batch.

**Advance 3 — Wire tool execution (not yet done).**

- **→ METRIC:** same held-out suite, re-run pending.
- **: SUPPOSE:** with `single_agent` / `planner_executor` tool dispatch wired to a
  real MCP client, `tool_correctness` moves off zero and the
  `straightforward` / `missing_evidence` families reach terminal correct states.
- **— RESULT:** *pending* — the `# stub for MVP` comments are still in the tree.
  Top open item in [`phases/build-report.md`](phases/build-report.md).

### SOLUTION (what shipped)

- **Topology:** fixed graph is the default (ADR-0006), chosen on matched-budget
  token/step count — **not** on `task_success`, which is not yet positive.
- **Provider:** `LLMAdapter` boundary; `minimax` live, `local-fake` in CI; no
  provider name in graph code (ADR-0003).
- **MCP:** custom document server (2 tools) + pinned filesystem server scoped to
  `fixtures/docs/` only, spec `2026-07-28`, stdio (ADR-0002). A negative test
  asserts `/etc/passwd` returns `permission_denied`. Not reachable from a run.
- **Dataset:** 30 cases, 18/6/6, held-out content-hashed and frozen before
  Phase 3 (ADR-0004); the freeze is test-enforced.
- **Safety:** JWT principal drives identity; the mock ticket ledger is idempotent
  and rejects mutated args; OTel traces are redacted before export.
- **Delivery:** Docker Compose stack, Alembic migrations, offline CI
  (`local-fake`), 154 tests, ruff clean.

Résumé line, filled only from published results:

> Built a LangGraph/FastAPI support agent with an MCP document server and a
> 30-case frozen benchmark; ran 42 live experiments on `MiniMax-M3` for $0.03
> comparing 3 prompts and 2 topologies under a matched budget, and shipped the
> fixed graph.

---

## Reference docs

| Doc | Path |
|---|---|
| Design proposal (scope SSOT) | [`docs/proposals/agentops-workbench-proposal.md`](docs/proposals/agentops-workbench-proposal.md) |
| Phase index | [`phases/index.md`](phases/index.md) |
| Build audit (per-step verdicts) | [`phases/build-report.md`](phases/build-report.md) |
| ADR catalogue | [`docs/adr/README.md`](docs/adr/README.md) |
| App README (architecture + layout) | [`apps/agentops-workbench/README.md`](apps/agentops-workbench/README.md) |
| Scope in / out | [`apps/agentops-workbench/docs/scope.md`](apps/agentops-workbench/docs/scope.md) |
| Evidence card | [`apps/agentops-workbench/docs/EVIDENCE_CARD.md`](apps/agentops-workbench/docs/EVIDENCE_CARD.md) |
| Operator runbook | [`apps/agentops-workbench/docs/RUNBOOK.md`](apps/agentops-workbench/docs/RUNBOOK.md) |
| 5-minute demo script | [`apps/agentops-workbench/docs/demo.md`](apps/agentops-workbench/docs/demo.md) |

## License

The `apps/agentops-workbench/` application is MIT
([`apps/agentops-workbench/LICENSE`](apps/agentops-workbench/LICENSE)).
