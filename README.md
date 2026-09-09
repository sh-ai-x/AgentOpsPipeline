# AgentOps Workbench

A support-operations agent that turns a repository issue into a *grounded*
answer and an *approval-gated* ticket draft, plus an experiment workbench
that compares prompt, workflow-topology and tool-integration choices on a
frozen 30-case benchmark.

The contribution is one complete application and one defensible
optimization study — not a general-purpose agent framework. LangGraph from
the first release, LangChain integrations, real MCP protocol calls to local
controlled services.

The application lives in [`apps/agentops-workbench/`](apps/agentops-workbench/).

---

## What's in here

```
apps/agentops-workbench/
  src/agentops_workbench/
    api/server.py              # FastAPI + HS256 JWT
    graph/{fixed,single_agent,planner_executor,topology,state}.py
    llm/{adapter,factory,local_fake,minimax,openai_compat}.py
    mcp/mcp_servers/{document,filesystem}/...
    benchmark/{scorers,load}.py
    experiments/{held_out,run_held_out}.py
    mocks/tickets.py           # idempotent mock ticket ledger
    observability/otel.py      # tracer + redaction
  fixtures/cases/{dev,val,held_out,pilot}/case-*.json
  fixtures/docs/doc-001..008-*.md
  experiments/{prompts-v1,held-out-v1}/
  docs/{scope.md,RUNBOOK.md,EVIDENCE_CARD.md,demo.md,adr/0001..0006-*.md}
  docker/docker-compose.yml    # postgres + api + worker + streamlit + mcp-document
docs/proposals/                # design proposal — scope source of record
```

---

## Progress

### Pipeline history (PRs)

| PR | Title | State | Outcome |
|---|---|---|---|
| #1 | AgentOps Workbench design proposal (+ styled HTML) | merged | Scope frozen in `docs/proposals/agentops-workbench-proposal.md` |
| #2 | Pin MiniMax as default live provider | merged | `provider=minimax` live / `local-fake` CI (ADR-0003) |
| #3 | Pivot proposal to LLM Wiki Search | **closed, not merged** | Rejected — scope drift away from the job spec |
| #5 | Import `apps/agentops-workbench/` + run held-out experiment | **open** | Single-repo consolidation; held-out + prompt experiments |

### Build phases (from the proposal's Step-by-Step Build Guide)

| Phase | Scope | State |
|---|---|---|
| 0 — Scope & ground truth | user workflow, typed contracts, ADRs, pilot cases | ✅ `docs/scope.md`, `docs/adr/0001–0006`, 30 pilot cases |
| 1 — Runnable agent & API | fixed LangGraph graph, FastAPI + JWT, fake + live adapters, mock ledger, Streamlit | ✅ shipped; Streamlit now calls the real API (`d7318f7`) |
| 2 — MCP & reliable tool use | document MCP server, pinned filesystem server, timeouts / error envelopes / scope guard, restart + duplicate-delivery tests | ✅ shipped; `mcp==2.2.0`, spec `2026-07-28`, stdio only |
| 3 — Benchmark curation & prompt experiments | 30 cases 18/6/6, frozen held-out hash, node/task scorers, 3-prompt comparison | ✅ dataset frozen; `experiments/prompts-v1/` published |
| 4 — Topology & planning experiments | single-agent + planner/executor variants, matched-budget comparison, shipping choice | 🟡 registry + variants shipped, ADR-0006 picks the fixed graph; full `experiments/topology-v1/` report not yet published |
| 5 — Failure evidence & delivery | redacted OTel export, seeded regression, Docker Compose, Alembic, offline CI | 🟡 Docker + Alembic + OTel redaction shipped; seeded-regression walkthrough pending |
| 6 — Held-out evaluation & portfolio | budgeted held-out run, raw outcomes + uncertainty, evidence card, demo | 🟡 harness + `experiments/held-out-v1/` exist; **numbers are pre-fix and need a re-run** (see below) |

### Test / lint status

```
cd apps/agentops-workbench
uv run pytest -q      # ~138 tests passing
uv run ruff check .   # clean
```

### Known gap

The `experiments/prompts-v1/` and `experiments/held-out-v1/` runs recorded
**0% task success**. Post-run debugging (commits `ace4270`, `1f5f8c4`,
`d7318f7`, `d081dc0`) found and fixed the root causes — retrieval was not
wired into the classifier, the classifier was non-deterministic, and
`docs_dir` was not configurable. **The experiments have not been re-run
against `provider=minimax` since those fixes.** Until they are, treat the
published numbers as a debugging baseline, not a result.

---

## Usage

### Run the workbench

```bash
cd apps/agentops-workbench
uv sync --extra dev

# Live experiments need a MiniMax key; CI / tests do not.
cp .env.example .env
# edit .env: MINIMAX_API_KEY=...   (never commit a populated .env)

uv run pytest -q                                             # offline, provider=local-fake
uv run uvicorn agentops_workbench.api.server:app --port 8000 # REST API
uv run streamlit run streamlit_app/app.py                    # submit / inspect / approve UI
```

REST surface (HS256 JWT, `AGENTOPS_JWT_SECRET` in `.env`):

```
POST /v1/runs                 # submit an issue -> queued run
GET  /v1/runs/{id}            # state + answer + ticket draft + trace_id
POST /v1/runs/{id}/cancel     # stop future work (no rollback of done effects)
POST /v1/actions/{id}/approve # bind user+run+tool+args+nonce, then publish_ticket
```

Full Docker stack (postgres + api + worker + streamlit + mcp-document):

```bash
docker compose -f docker/docker-compose.yml up
```

### Run the experiments

```bash
cd apps/agentops-workbench

# 3-prompt comparison on the 6 validation cases
uv run python -m agentops_workbench.experiments.run_prompts

# Budgeted held-out run (6 cases x 2 trials x 2 topologies = 24 runs)
AGENTOPS_PROVIDER=minimax \
  uv run python -m agentops_workbench.experiments.run_held_out
# -> experiments/held-out-v1/{outcomes.jsonl, manifest.json,
#                             failed_cases.md, uncertainty.md}
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
commits `ace4270` (retrieval → classifier), `1f5f8c4` (deterministic classifier + permissive answer prompt), `d7318f7` (Streamlit calls the real API), `d081dc0` (env-configurable `docs_dir`, accurate OTel ns timestamps).

- **→ METRIC:** same held-out suite, re-run pending.
- **: SUPPOSE:** with retrieval wired and the classifier deterministic, the `straightforward` and `missing_evidence` families reach terminal correct states; `tool_correctness` moves off zero.
- **— RESULT:** *pending* — not yet re-run against `provider=minimax`. Recorded as the top open item in `docs/EVIDENCE_CARD.md` limitations.

### SOLUTION (what shipped)

- **Topology:** fixed graph is the default (`graph_version="fixed-v1"`, ADR-0006). Single-agent and planner/executor stay selectable through the `run_topology(name, ...)` registry for future experiments. Chosen on matched-budget step count / token usage, *not* on `task_success` (which is not yet positive).
- **Provider:** `LLMAdapter` boundary; `provider=minimax` live, `local-fake` in CI, `openai`/`anthropic` per-experiment. No provider name appears in graph code (ADR-0003).
- **MCP:** custom document server + pinned `@modelcontextprotocol/server-filesystem` scoped to `fixtures/docs/` only, spec `2026-07-28`, stdio (ADR-0002). A negative test asserts `/etc/passwd` returns `permission_denied`.
- **Dataset:** 30 cases, 18 dev / 6 val / 6 held-out, held-out content-hashed into `fixtures/cases/HELD_OUT_SHA256.txt` and frozen before Phase 3 (ADR-0004).
- **Safety:** JWT principal drives identity; approval binds user + run + tool + canonical args + expiry + one-use nonce; mock ticket ledger is idempotent and rejects mutated args; OTel traces are redacted (5 patterns) before export.
- **Delivery:** Docker Compose stack, Alembic migrations, offline CI (`local-fake`), ~138 tests, ruff clean.

Résumé line, filled only from published results:

> Built a LangGraph/FastAPI support agent integrating 2 MCP servers;
> compared 3 prompts and 2 workflow topologies on a frozen 6-case held-out
> set under a matched budget, and shipped the fixed graph.

---

## Reference docs

| Doc | Path |
|---|---|
| Design proposal (scope SSOT) | `docs/proposals/agentops-workbench-proposal.md` |
| Proposal, styled HTML | `docs/proposals/accepted/agentops-workbench/main.html` |
| App README (architecture + layout) | `apps/agentops-workbench/README.md` |
| Scope in / out | `apps/agentops-workbench/docs/scope.md` |
| ADRs 0001–0006 | `apps/agentops-workbench/docs/adr/` |
| Evidence card | `apps/agentops-workbench/docs/EVIDENCE_CARD.md` |
| Operator runbook | `apps/agentops-workbench/docs/RUNBOOK.md` |
| 5-minute demo script | `apps/agentops-workbench/docs/demo.md` |

---

## License

The `apps/agentops-workbench/` application is MIT — see
`apps/agentops-workbench/LICENSE`.
