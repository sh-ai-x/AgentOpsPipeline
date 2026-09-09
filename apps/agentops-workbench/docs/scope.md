# Scope — AgentOps Workbench

## User workflow

An engineering support user submits a software issue (free text + repo
context). The system:

1. Retrieves versioned documentation from the document MCP server.
2. Asks for clarification when the task is ambiguous.
3. Proposes a supported answer.
4. Optionally drafts a ticket.
5. **Publishes only after the user approves** a server-validated action
   record bound to user + run + tool + canonical args + expiry + nonce.

## MVP tools

- `search_docs(query, top_k)`
- `read_document(doc_id, offset, limit)`
- `get_issue(issue_id)`
- `create_ticket_draft(title, body)`
- `publish_ticket(action_key, ticket_draft_id)` — gated by approval.

## Permissions

- Documents: read-only via the document MCP server (fixture corpus).
- Tools: each `BenchmarkCase.allowed_tools` whitelist enforces per-case.
- Tickets: publish is the only mutating effect; it goes to a local mock
  ticket ledger, never to a real external service.

## Excluded features (out of MVP)

- Fine-tuning, Kubernetes, autonomous deployment.
- ML router baseline (TF-IDF / logistic regression).
- LangSmith export, A2A, second SDK.
- pgvector / vector search.
- Synthetic candidate generator pipeline.
- UI polish beyond Streamlit approve/inspect.
- Streamable-HTTP MCP transport (stdio only for MVP).

## Task families (6)

straightforward answer · multi-document answer · ambiguous request ·
missing evidence · conflicting/stale documentation · tool failure
