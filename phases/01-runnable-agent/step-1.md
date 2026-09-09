# Step 2 — Runnable agent + FastAPI + local-fake adapter

**Phase:** 1 (proposal §"Phase 1: Runnable Agent and API")
**Branch:** `feat/01-runnable-agent`
**Worktree:** `.worktrees/01-runnable-agent`
**Methodology:** TDD
**Estimated:** 1.5 weeks

## Work items

### 2.1 LLMAdapter interface

- `src/agentops_workbench/llm/adapter.py` — `LLMAdapter` ABC with `chat(messages, **kw) -> ChatResult` returning `Usage(provider, model, prompt_tokens, completion_tokens, total_tokens, cost_usd)`.
- `adapters/local_fake.py` — deterministic scripted responses from `fixtures/llm/scripts/<test>.jsonl`.
- `adapters/minimax.py` — `ChatOpenAI(base_url=MINIMAX_BASE_URL, api_key=...)` with provider label `"minimax"`.

### 2.2 Fixed LangGraph workflow

- `src/agentops_workbench/graph/fixed.py` — `StateGraph(MessagesState)`:
  - `retrieve` → `classify` → (conditional: `answer` | `refuse` | `clarify`).
- State holds: `messages`, `evidence`, `route`, `run_id`.
- Bounded steps + deadline enforced in the graph runtime.

### 2.3 FastAPI surface

- `POST /v1/runs` — JWT-authenticated; returns `{id, state: 'queued'}`.
- `GET /v1/runs/{id}` — returns state, evidence refs, last error, token usage.
- `POST /v1/runs/{id}/cancel` — sets state to `cancelling`; refuses new tool calls.
- `POST /v1/actions/{id}/approve` — action-bound approval (user + run + tool + canonical args + expiry + nonce).
- `src/agentops_workbench/api/auth.py` — HS256 JWT, dev secret in `.env` (rejected if `.env` absent in non-dev mode).

### 2.4 Persistence

- Postgres + SQLAlchemy + Alembic.
- Tables: `runs`, `tool_calls`, `actions`, `experiments`.
- Checkpoints per LangGraph thread.

### 2.5 Mock ticket ledger

- `src/agentops_workbench/mocks/tickets.py` — in-memory + persisted ledger.
- Action key = `(run_id, tool_name, canonical_args_hash)`; second dispatch with same key returns existing outcome without re-publishing.

### 2.6 Streamlit skeleton

- Submit a task; see retrieval evidence; see proposed answer; see ticket draft; click approve/cancel.

## TDD plan

1. **Red** `tests/test_adapter_local_fake.py` — scripted response replay; usage token counts.
2. **Red** `tests/test_graph_fixed.py` — straight answer path; missing evidence refuses; ambiguous clarifies.
3. **Red** `tests/test_api_runs.py` — auth gate, run creation, state transitions, cancellation.
4. **Red** `tests/test_action_approval.py` — approval binding, replay rejection, expiry.
5. **Red** `tests/test_ticket_ledger.py` — duplicate dispatch does not duplicate mock effect.

## Exit criteria

- `docker compose up` brings up Postgres + API + Streamlit.
- `curl -H 'Authorization: Bearer ...' /v1/runs` accepts and persists.
- End-to-end demo: submit "how do I configure retries?" → answer + ticket draft → approve → one entry in mock ledger.
- Missing-evidence task returns supported refusal, not empty string.
- Failed tool is visible (state `failed`, error string, no zombie retries).
- All red→green→refactor cycles land their regression tests.

## Risks

- Provider-specific code leaking into the graph (R2 mitigation: adapter boundary strictly at `LLMAdapter`).
- Cancellation race: ensure `cancel` is checked before every tool dispatch, not just at planning.
