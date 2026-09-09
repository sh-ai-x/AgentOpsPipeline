# Step 3 — MCP document server + filesystem pin + recovery

**Phase:** 2 (proposal §"Phase 2: MCP and Reliable Tool Use")
**Branch:** `feat/02-mcp-integration`
**Worktree:** `.worktrees/02-mcp-integration`
**Methodology:** TDD
**Estimated:** 1.0 week

## Work items

### 3.1 Custom document MCP server (stdio)

- `mcp_servers/document/server.py` — FastMCP-style server (stdio transport).
- Tools exposed: `search_docs(query, top_k)`, `read_document(doc_id, offset, limit)`.
- Resources: `doc://<id>` returning fixture docs under `fixtures/docs/`.
- Pin protocol revision `2026-07-28` in `initialize` handshake.

### 3.2 Filesystem MCP pin

- `@modelcontextprotocol/server-filesystem@<pinned-version>` as a subprocess.
- Configured to expose ONLY `fixtures/docs/`. Refuses anything outside that root.
- Version pin recorded in `pyproject.toml` and ADR-0005 amendment.

### 3.3 MCP client + identity binding

- `src/agentops_workbench/mcp/client.py` — async client; tool-call timeout (5s); capability handshake on connect.
- Identity passed via `_meta.principal_id` per the proposal's §"Auth and Identity".
- Tool-call dispatcher rejects cross-scope calls (returns `permission_denied`).

### 3.4 Error normalization

- All MCP errors wrapped as `MCPError(kind, message, source)`.
- `kind ∈ {timeout, malformed, unsupported_capability, permission_denied, disconnect}`.

### 3.5 Recovery + duplicate-delivery tests

- Worker restart: recover in-flight `queued`/`running` runs whose lease has expired.
- Duplicate publish: same `action_key` returns existing outcome; new dispatch with mutated args raises.

## TDD plan

1. **Red** `tests/test_mcp_document_server.py` — discovery, schema, search, read with offset/limit.
2. **Red** `tests/test_mcp_filesystem_pin.py` — refuses paths outside `fixtures/docs/`.
3. **Red** `tests/test_mcp_client_timeout.py` — slow server returns `MCPError(kind='timeout')`.
4. **Red** `tests/test_mcp_duplicate_publish.py` — duplicate `publish_ticket` with same `action_key` returns existing outcome.
5. **Red** `tests/test_mcp_server_disconnect.py` — abrupt disconnect → graceful `MCPError(kind='disconnect')`; reconnect resumes.

## Exit criteria

- All MCP integration tests pass against the pinned SDK + spec revision.
- A repeated `publish_ticket` action does not duplicate the mock ledger entry.
- Restart of the worker mid-run recovers the job; the resumed run completes with the same evidence.
- Cross-scope tool call returns `permission_denied` and is logged.

## Risks

- Spec drift (R3): record the pinned revision; have an exit-criterion that fails if the server's reported `supportedVersions` does not include `2026-07-28`.
- Filesystem MCP granting more scope than fixtures: a test must prove the negative (attempting `/etc/passwd` returns `permission_denied`).
