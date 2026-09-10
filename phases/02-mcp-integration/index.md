# 02-mcp-integration

> Phase 2 — MCP document server + filesystem pin + recovery

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Phase 2"
- **Canonical step plan:** `.dev-kit/round-1/phases/build/step3.md` — local planning artefact, not tracked in git (`.dev-kit/round-1/` is `.gitignore`d). This page is the tracked, self-contained promotion of it.
- **Estimated:** 1.0 week (original plan value, not measured effort)
- **Exit criterion:** Tools work through the protocol and a repeated action does not duplicate the mock effect
- **Status:** shipped — merged into `apps/agentops-workbench/` via PR #8
- **Build output:** [`step3-output.json`](step3-output.json) — reconstructed step record (see [`../build-report.md`](../build-report.md))

## Deliverables (planned)

- Custom document MCP server (stdio, spec `2026-07-28`): `search_docs`, `read_document`
- Pinned `@modelcontextprotocol/server-filesystem`, scoped to `fixtures/docs/` only
- Call validation + timeouts + error normalization; identity-bound approval
- Recovery + duplicate-delivery tests

## What shipped

- `src/agentops_workbench/mcp/mcp_servers/{document,filesystem}/`
- 5 MVP tools: `search_docs`, `read_document`, `get_issue`, `create_ticket_draft`, `publish_ticket`
- Negative test: path outside `fixtures/docs/` returns `permission_denied`
- `approved_by` derived from the JWT (PR #8, finding F01)

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
- Implemented in: [`../../apps/agentops-workbench/`](../../apps/agentops-workbench/)
- Shipped summary: [`../../apps/agentops-workbench/docs/EVIDENCE_CARD.md`](../../apps/agentops-workbench/docs/EVIDENCE_CARD.md)
- Root phase index: [`../index.md`](../index.md)
