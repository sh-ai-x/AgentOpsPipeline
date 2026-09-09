# 02-mcp-integration

> Phase 2 — MCP document server + filesystem pin + recovery

- **Branch:** `feat/02-mcp-integration`
- **Estimated:** 1.0 week(s)
- **Step doc:** [step-2.md](step-2.md) (canonical: `.dev-kit/round-1/phases/build/step2.md`)
- **Step branch:** `feat/02-mcp-integration`
- **Exit criterion:** Tools work through the protocol and a repeated action does not duplicate the mock effect

## Title

MCP document server + filesystem pin + recovery

## Deliverables

- custom document MCP server (stdio, fixture-only)\n- `@modelcontextprotocol/server-filesystem` pin (fixture-only)\n- call validation + timeouts + error normalization\n- identity-bound approval\n- recovery + duplicate-delivery tests

## Cross-references

- Source proposal: `docs/proposals/agentops-workbench-proposal.md`
- Implemented in: `apps/agentops-workbench/`
- Step plan (authoritative): `.dev-kit/round-1/phases/build/step2.md`
- Step plan (mirror): `phases/02-mcp-integration/step-2.md`
