# Checkpointing

LangGraph checkpointing persists graph state between steps so a run can be
inspected or replayed later.

## Postgres checkpointer

The PostgresCheckpointer writes checkpoint state to a Postgres table on
every superstep. Enable it by passing a `PostgresSaver` instance as the
graph's `checkpointer` argument when compiling.
