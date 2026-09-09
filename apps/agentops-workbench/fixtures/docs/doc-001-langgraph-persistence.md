# LangGraph persistence

LangGraph supports durable execution via checkpointers. The
`PostgresCheckpointer` stores each state transition in a `checkpoints`
table, keyed by thread_id. On worker restart, resume from the last
checkpoint. `SqliteCheckpointer` is the single-node equivalent.

> Source: paraphrased from langgraph docs (Apache-2.0).
