# 5-minute demo script — AgentOps Workbench

## Beat 1 (0:00 - 0:30): submit a task

```
```bash
# terminal 1: bring up the API
cd ~/dev/agentops-workbench
AGENTOPS_PROVIDER=minimax uv run uvicorn agentops_workbench.api.server:app --port 8000
```
```

Open http://127.0.0.1:8000/docs, scroll to POST /v1/runs. Use the dev token
from the Streamlit sidebar (terminal 2) as the Bearer. Submit:

```json
{ "task": "How do I configure LangGraph checkpointing with Postgres?" }
```

Show the JSON response: id, state (succeeded), answer.

## Beat 2 (0:30 - 1:30): MCP calls + tool trace

Show the redacted trace at `runs/<id>/trace.otel.jsonl`. Walk through one
span: `model_call -> classify -> tool_call (search_docs) -> model_call ->
answer`. Highlight the redaction pass (api_key / Bearer tokens become
`[REDACTED]`).

## Beat 3 (1:30 - 2:30): topology comparison

```
```bash
uv run python -m agentops_workbench.experiments.run_held_out
cat experiments/held-out-v1/manifest.json
cat experiments/held-out-v1/outcomes.jsonl | wc -l   # 24
```
```

Show the 24-run summary: per-topology task_success, per-family breakdown.

## Beat 4 (2:30 - 3:30): seeded regression

Run the failure-to-regression test:

```
```bash
uv run pytest tests/test_observability.py::test_seeded_failure_is_caught_by_red_test -v
```
```

If the test fails, the demo shows the failure->regression walkthrough.

## Beat 5 (3:30 - 4:30): held-out vs dev

Show `experiments/held-out-v1/failed_cases.md` and `uncertainty.md`. Note
the held-out SHA freeze (`fixtures/cases/HELD_OUT_SHA256.txt`) and that the
tuning configs in step 4 never touched held-out cases.

## Beat 6 (4:30 - 5:00): evidence card

Show `docs/EVIDENCE_CARD.md`. Mention the resumé bullet template from the
proposal, filled only from published numbers.
