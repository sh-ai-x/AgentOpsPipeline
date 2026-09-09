# ADR-0001: LangGraph as the workflow engine

## Status

Accepted (2026-09-08).

## Decision

Use LangGraph (`langgraph==1.2.11`) for the agent runtime.

## Consequences

- Explicit state, conditional routing, checkpointers, interrupts/resume —
  matches the proposal's MVP requirements.
- LangChain chat-model wrapper per provider gives us a single
  `LLMAdapter` boundary so the graph code is provider-agnostic.
- Alternatives (raw OpenAI Agents SDK, custom async DAG) were rejected
  for not offering checkpointing + interrupts out of the box.
