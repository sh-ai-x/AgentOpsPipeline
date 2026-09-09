# ADR-0002: MCP server boundaries

## Status

Accepted (2026-09-08).

## Decision

- Custom document MCP server using the official Python SDK
  (`mcp==2.2.0`).
- Transport: **stdio only** for the MVP (Streamable HTTP deferred).
- One pinned external MCP server:
  `@modelcontextprotocol/server-filesystem` configured to expose ONLY
  `fixtures/docs/`. Refuses any path outside that root.
- Pin the MCP spec revision spoken in `initialize` to `2026-07-28`.

## Consequences

- Local-only MCP keeps the demo deterministic; no auth server needed.
- Streamable HTTP deferred: revisit when multi-client support is a real
  requirement (out of MVP).
- Filesystem server scope must be enforced by a test (negative case
  attempting `/etc/passwd` must return `permission_denied`).
