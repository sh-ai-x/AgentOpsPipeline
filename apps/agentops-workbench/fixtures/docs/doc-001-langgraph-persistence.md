# LangGraph persistence

LangGraph supports durable execution via checkpointers. The
`PostgresCheckpointer` (from `langgraph-checkpoint-postgres`) stores each
state transition in a `checkpoints` table, keyed by `thread_id`. On worker
restart, resume from the last checkpoint. `SqliteCheckpointer`
(`langgraph-checkpoint-sqlite`) is the single-node equivalent.

## Setup with PostgreSQL

1. Install the extras: `pip install langgraph-checkpoint-postgres psycopg[binary]`
2. Construct the checkpointer from a libpq connection string:

```python
from langgraph.checkpoint.postgres import PostgresCheckpointer

checkpointer = PostgresCheckpointer.from_conn_string(
    "postgresql://USER:PASSWORD@HOST:5432/DBNAME"
)
```

3. Pass it into your compiled graph:

```python
from langgraph.graph import StateGraph

graph = StateGraph(MyState).compile(checkpointer=checkpointer)
```

4. Invoke with a stable `thread_id` so each run can resume:

```python
config = {"configurable": {"thread_id": "user-42-thread-1"}}
result = graph.invoke({"messages": [("user", task)]}, config=config)
```

## Schema

`PostgresCheckpointer` writes three tables on first use:

- `checkpoints` — one row per state transition (state blob + metadata).
- `checkpoint_blobs` — the serialized state payload.
- `checkpoint_writes` — pending writes that haven't been committed yet.

You create these with the package's migration helper:

```python
from langgraph.checkpoint.postgres import PostgresCheckpointer
PostgresCheckpointer.setup(checkpointer.conn)  # idempotent
```

## Resume semantics

If a worker crashes mid-run, the next invocation with the same
`thread_id` loads the most recent checkpoint and replays from there.
All state writes before the crash are preserved. No work is lost.

## Postgres vs Sqlite

- Use **Postgres** for multi-instance workers (e.g. several pods serving
  the same graph concurrently) and for durable cross-restart state.
- Use **Sqlite** for single-node dev / notebook work — zero-config,
  file-based, fast iteration.
- Switching requires changing only the `checkpointer` argument; the
  graph code is identical.

> Source: paraphrased from langgraph docs (Apache-2.0).
