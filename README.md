# AgentOps Workbench

A support-operations agent that turns a repository issue into a *grounded*
answer and an *approval-gated* ticket draft, plus an experiment workbench
that compares prompt, workflow-topology and tool-integration choices on a
frozen 30-case benchmark.

The contribution is one complete application and one defensible
optimization study — not a general-purpose agent framework. LangGraph from
the first release, LangChain integrations, real MCP protocol calls to local
controlled services.

Scope of record: [`docs/proposals/agentops-workbench-proposal.md`](docs/proposals/agentops-workbench-proposal.md).

> **Repo status.** This README and the design proposal are on `main`. The
> application itself (`apps/agentops-workbench/` — `src/`, `fixtures/`,
> `experiments/`, `docker/`, ~138 tests) lands in a separate import PR.
> Paths under `apps/agentops-workbench/` referenced below resolve once
> that PR merges.

---

## Progress

### Build phases (from the proposal's Step-by-Step Build Guide)

| Phase | Scope | State |
|---|---|---|
| 0 — Scope & ground truth | user workflow, typed contracts, ADRs, pilot cases | ✅ proposal, `docs/adr/0001–0006`, 30 pilot cases |
| 1 — Runnable agent & API | fixed LangGraph graph, FastAPI + JWT, fake + live adapters, mock ledger, Streamlit | ✅ built; Streamlit calls the real API |
| 2 — MCP & reliable tool use | document MCP server, pinned filesystem server, timeouts / error envelopes / scope guard, restart + duplicate-delivery tests | ✅ built; `mcp==2.2.0`, spec `2026-07-28`, stdio only |
| 3 — Benchmark curation & prompt experiments | 30 cases 18/6/6, frozen held-out hash, node/task scorers, 3-prompt comparison | ✅ dataset frozen; `experiments/prompts-v1/` published |
| 4 — Topology & planning experiments | single-agent + planner/executor variants, matched-budget comparison, shipping choice | 🟡 registry + variants built, ADR-0006 picks the fixed graph; full `experiments/topology-v1/` report not yet published |
| 5 — Failure evidence & delivery | redacted OTel export, seeded regression, Docker Compose, Alembic, offline CI | 🟡 Docker + Alembic + OTel redaction built; seeded-regression walkthrough pending |
| 6 — Held-out evaluation & portfolio | budgeted held-out run, raw outcomes + uncertainty, evidence card, demo | 🟡 harness + `experiments/held-out-v1/` exist; **numbers are pre-fix and need a re-run** (see below) |

### Design decisions (ADRs, land with the import PR)

| ADR | Decision |
|---|---|
| 0001 | LangGraph (`langgraph==1.2.11`) as the workflow engine |
| 0002 | MCP boundaries — custom document server + pinned `@modelcontextprotocol/server-filesystem`, stdio, spec `2026-07-28`, fixture-only scope |
| 0003 | Provider abstraction — single `LLMAdapter`; `minimax` live / `local-fake` CI; no provider name in graph code |
| 0004 | Dataset separation — 30 cases 18 dev / 6 val / 6 held-out; held-out content-hashed and frozen before Phase 3 |
| 0006 | Ship the fixed graph as the default topology |

### Known gap

The `prompts-v1` and `held-out-v1` runs recorded **0% task success**.
Post-run debugging found the root causes — retrieval was not wired into
the classifier, the classifier was non-deterministic, and `docs_dir` was
not configurable — and fixed them. **The experiments have not been re-run
against `provider=minimax` since those fixes.** Until they are, treat the
published numbers as a debugging baseline, not a result.

---

## Usage

*(after the workbench import PR merges)*

```bash
cd apps/agentops-workbench
uv sync --extra dev

cp .env.example .env          # MINIMAX_API_KEY for live experiments; CI needs none

uv run pytest -q                                             # offline, provider=local-fake
uv run uvicorn agentops_workbench.api.server:app --port 8000 # REST API
uv run streamlit run streamlit_app/app.py                    # submit / inspect / approve UI
docker compose -f docker/docker-compose.yml up               # postgres + api + worker + streamlit + mcp-document
```

REST surface (HS256 JWT):

```
POST /v1/runs                 # submit an issue -> queued run
GET  /v1/runs/{id}            # state + answer + ticket draft + trace_id
POST /v1/runs/{id}/cancel     # stop future work (no rollback of done effects)
POST /v1/actions/{id}/approve # bind user+run+tool+args+nonce, then publish_ticket
```

Experiments:

```bash
uv run python -m agentops_workbench.experiments.run_prompts     # 3 prompts x 6 val cases
AGENTOPS_PROVIDER=minimax \
  uv run python -m agentops_workbench.experiments.run_held_out  # 6 cases x 2 trials x 2 topologies
# SpendCeiling (default $5.00) is enforced before any live call.
```

---

## PROBLEM · ANALYSIS · [ ADVANCE → METRIC : SUPPOSE — RESULT ] · SOLUTION

The optimization study, in the notation above: one problem, its analysis,
an iterated experiment loop where each **advance** is bound to a **metric**,
carries a **supposition** stated *before* the run, and records the
**result**, then the **solution** that shipped.

### PROBLEM

Given a repository issue, produce a *grounded* answer and an
*approval-gated* ticket draft — refusing or asking for clarification when
the evidence does not support an answer — and decide, with evidence, which
prompt and which workflow topology to ship. Not "build another agent
framework": build one application and one defensible measurement.

### ANALYSIS

- **Correctness is multi-axis.** A run can retrieve the right documents and
  still call the wrong tool; it can answer fluently with no grounding. So
  the scorecard separates `task_success`, `retrieval_recall@k`,
  `tool_correctness`, reliability, and cost/latency — no single number.
- **Topology comparison is only meaningful under a matched budget.** Fixed
  graph, single agent, and planner/executor must share the corpus, prompt
  family, model, tool permissions, and the outer `MAX_STEPS=8` cap (R4).
  Any drift invalidates the comparison.
- **The held-out set is tiny by design (6 cases).** The proposal labels its
  own numbers "illustrative, not statistically settled." Extra trials of
  one case do not create independent scenarios; temperature 0 does not
  guarantee reproducibility.
- **The model chooses nothing that matters.** Identity comes from the JWT
  principal, not the model. Permissions and approval are re-checked
  immediately before an effect, and `publish_ticket` is idempotent on a
  stable action key so a crash-after-dispatch does not double-publish.

### [ ADVANCE → METRIC : SUPPOSE — RESULT ]

**Advance 1 — Prompt family, under a fixed graph**
`experiments/prompts-v1/` · 3 prompts × 6 validation cases = 18 runs, identical budget / model / permissions.

- **→ METRIC:** `task_success`, prompt/completion tokens, latency.
- **: SUPPOSE:** `v2_structured` (explicit "refuse / clarify when unsupported" instructions) beats `v1_baseline`; `v3_minimal` (no system instruction) is worst.
- **— RESULT:** `v1_baseline` 0/6 · `v2_structured` 0/6 · `v3_minimal` 0/6. The supposition about *ordering* was untestable — every prompt scored zero because a wiring defect upstream of the prompt (retrieval output never reached the classifier) capped the ceiling at zero. `v3_minimal` was still published as the documented unsuccessful change: with no system instruction the model cannot satisfy the "supported refusal / clarification" requirement regardless of retrieval.

**Advance 2 — Topology, on the frozen held-out set**
`experiments/held-out-v1/` · fixed vs. single_agent · 6 cases × 2 trials × 2 topologies = 24 runs · `provider=minimax`, model `MiniMax-M3`, `v1_baseline`, spend ceiling $5.00.

- **→ METRIC:** `task_success`, `retrieval_recall`, `tool_correctness`, `cost_usd`, `duration_ms`, per family.
- **: SUPPOSE:** the fixed graph reaches the same outcomes at lower cost; the single agent may edge ahead on the `multi_doc` family by chaining reads.
- **— RESULT:** `fixed` 0/12 · `single_agent` 0/12 `task_success`. But the *sub-metrics localised the fault*: `retrieval_recall` was 1.0 on 5 of 6 families (0.5 on `multi_doc`) while `tool_correctness` was 0.0 everywhere — the agent fetched the right evidence and then never issued a correct tool call. The single agent spent 2–10× the completion tokens (e.g. 513 vs. 54 on `case-025`) for no gain, which *does* support the "simpler workflow may win" half of the supposition. Live cost was ~\$0.0003–0.0014 per run, well under ceiling.

**Advance 3 — Fix the wiring the experiments exposed**
retrieval → classifier, deterministic classifier + permissive answer prompt, Streamlit calls the real API, env-configurable `docs_dir`, accurate OTel ns timestamps.

- **→ METRIC:** same held-out suite, re-run pending.
- **: SUPPOSE:** with retrieval wired and the classifier deterministic, the `straightforward` and `missing_evidence` families reach terminal correct states; `tool_correctness` moves off zero.
- **— RESULT:** *pending* — not yet re-run against `provider=minimax`. Recorded as the top open item in the evidence card's limitations.

### SOLUTION (what shipped)

- **Topology:** fixed graph is the default (`graph_version="fixed-v1"`, ADR-0006). Single-agent and planner/executor stay selectable through the `run_topology(name, ...)` registry for future experiments. Chosen on matched-budget step count / token usage, *not* on `task_success` (which is not yet positive).
- **Provider:** `LLMAdapter` boundary; `provider=minimax` live, `local-fake` in CI, `openai`/`anthropic` per-experiment. No provider name appears in graph code (ADR-0003).
- **MCP:** custom document server + pinned `@modelcontextprotocol/server-filesystem` scoped to `fixtures/docs/` only, spec `2026-07-28`, stdio (ADR-0002). A negative test asserts `/etc/passwd` returns `permission_denied`.
- **Dataset:** 30 cases, 18 dev / 6 val / 6 held-out, held-out content-hashed into `fixtures/cases/HELD_OUT_SHA256.txt` and frozen before Phase 3 (ADR-0004).
- **Safety:** JWT principal drives identity; approval binds user + run + tool + canonical args + expiry + one-use nonce; mock ticket ledger is idempotent and rejects mutated args; OTel traces are redacted before export.
- **Delivery:** Docker Compose stack, Alembic migrations, offline CI (`local-fake`), ~138 tests, ruff clean.

Résumé line, filled only from published results:

> Built a LangGraph/FastAPI support agent integrating 2 MCP servers;
> compared 3 prompts and 2 workflow topologies on a frozen 6-case held-out
> set under a matched budget, and shipped the fixed graph.

---

## Reference docs

| Doc | Path | On `main`? |
|---|---|---|
| Design proposal (scope SSOT) | `docs/proposals/agentops-workbench-proposal.md` | ✅ |
| Proposal, styled HTML | `docs/proposals/accepted/agentops-workbench/main.html` | with import PR |
| App README (architecture + layout) | `apps/agentops-workbench/README.md` | with import PR |
| Scope in / out | `apps/agentops-workbench/docs/scope.md` | with import PR |
| ADRs 0001–0006 | `apps/agentops-workbench/docs/adr/` | with import PR |
| Evidence card | `apps/agentops-workbench/docs/EVIDENCE_CARD.md` | with import PR |
| Operator runbook | `apps/agentops-workbench/docs/RUNBOOK.md` | with import PR |
| 5-minute demo script | `apps/agentops-workbench/docs/demo.md` | with import PR |

---

## License

The `apps/agentops-workbench/` application is MIT (`apps/agentops-workbench/LICENSE`,
lands with the import PR).
