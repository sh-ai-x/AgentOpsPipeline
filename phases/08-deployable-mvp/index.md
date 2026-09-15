# 08-deployable-mvp

> Phase 8 — one flagship GitHub-URL CLI flow, wired from two of phase 7's
> five adapters; backend deployed and independently verifiable without
> the Streamlit UI.

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Update 2 (2026-09-13)"
- **Canonical step plan:** none — planned directly in the proposal and
  [ADR-0008](../../apps/agentops-workbench/docs/adr/0008-github-url-cli-and-deployment-target.md),
  same as phase 7.
- **Estimated:** not yet sized (no code written; see Status)
- **Exit criteria** (two, independently checkable):
  1. A reviewer runs `agentops-oss-helper <public-repo-url> --issue N`
     against a real public repository and gets a grounded answer or an
     explicit refusal, with zero manual setup beyond cloning this repo
     and setting one GitHub token env var.
  2. The backend is reachable at a public URL and a scripted smoke test
     hits `/v1/runs` and gets a real response with the Streamlit UI
     process not running anywhere.
- **Status:** **not started** — planning documents only (this phase +
  ADR-0008), no code
- **Build output:** none yet

## Why this phase exists

Phase 7 generalized the evidence-retrieval seam and PR #34 proved five
adapters work. That's a foundation, not a demo — "here are five
adapters, pick one" asks a reviewer to do the product thinking. This
phase narrows the *product* scope (not the code — all five adapters stay
general-purpose) to one concretely runnable flow, and takes the backend
from "works on my machine via `docker compose up`" to "reachable at a
URL, verifiable without the frontend."

## Deliverables (planned)

1. **`agentops-oss-helper` CLI** — parses a GitHub repo URL, acquires
   docs in bulk (`git sparse-checkout` locally, `codeload` tarball in a
   container — see ADR-0008 for why this split is forced, not chosen),
   flattens nested markdown for `WikiRagAdapter`'s non-recursive glob,
   and runs the new `oss_triage` topology
   (`graph_version="oss-triage-v1"`) below. No GitHub API for issues /
   PRs in the current scope — see ADR-0009 for the rationale and for the
   decision record of removing that source.
2. **`oss_triage` topology** — a fourth entry in `TOPOLOGIES`, four nodes
   (gather the WikiRagAdapter's top-k / classify sufficient-or-not /
   answer / refuse), one LLM call. Not `planner_executor` — see ADR-0008's
   Decision section for the four concrete reasons that topology can't
   host this flow as-is.
3. **Five named operational fixes** (ADR-0008 Consequences, minus the
   `GitHub API error handling` bullet since the GitHub source is out of
   scope for `oss-helper` after ADR-0009): `/healthz` route;
   `create_run` returns `202` + a poll path instead of running the graph
   synchronously in-request; `AGENTOPS_CODE_SHA` fails closed instead of
   defaulting to `"dev-sha"`; OTel redaction list gains `token`; a
   per-principal spend cap on `/v1/runs` (today `SpendCeiling` only
   guards the offline experiment runner).
4. **Backend/frontend split, falsifiable** — `streamlit` moves from
   `[project.dependencies]` to an optional `ui` extra in `pyproject.toml`.
   Acceptance: the deploy image builds and the smoke test in exit
   criterion 2 passes with Streamlit **absent** from the environment, not
   merely un-launched.
5. **Fly.io deployment** — one container, SQLite on a persistent volume
   (not Postgres — see ADR-0008 for the single-writer/kilobyte-dataset
   reasoning), scale-to-zero, a `deploy.yml` GitHub Actions job. Estimated
   ~$2–6/month; the one already-measured cost figure this reuses is
   `experiments/held-out-v1/manifest.json`'s $0.0124 / 24 LLM calls.

**Explicitly not in this phase:** the `EVIDENCE_SOURCES` registry/config
layer and Pillar 2's groundedness/drift eval layer — both still open per
phase 7's reconciled deliverables list, and neither is required for this
phase's two exit criteria.

**Scope change (2026-09-15):** the original phase plan referenced two
evidence sources (GitHub Issues/PRs via `GitHubIssueAdapter` plus docs via
`WikiRagAdapter`). The GitHub-Issues/PRs source has been dropped from
the `oss-helper` flagship flow per [ADR-0009](../../../docs/adr/0009-oss-helper-docs-only-scope.md):
the flagship flow is now docs-only. The remaining phase 8 deliverables
(items 1, 3, 4, 5) are unchanged in scope and content — only
"GitHub API error handling" in item 3 is removed.

## Known divergence this phase must close

`EvidenceRef` (PR #34) has no `uri` field, though ADR-0007 §2 specified
one. The CLI's stem→`(repo path, commit sha)` map (ADR-0008) supplies a
citation URL for the Wiki side without changing the adapter; the GitHub
adapter (which is no longer in scope for `oss-helper` per ADR-0009) is
not relied on for citations. Whether `EvidenceRef` itself should carry
`uri` so every adapter self-describes its citation, instead of every
caller reconstructing one, is an open question this phase does not resolve.

## Relationship to open PRs (as of 2026-09-15)

| PR | State | Bearing on this phase |
|----|-------|------------------------|
| #34 | merged | The five adapters this phase originally wired two of; only `WikiRagAdapter` is now used by `oss-helper` after ADR-0009 narrowed the scope. `search_evidence`/`read_evidence` signatures this phase's CLI calls directly. |
| #29 | open | `SubprocessDocumentClient` — unrelated lifecycle question (subprocess-per-call); this phase's adapters run in-process, no cold-start cost applies here. |
| #21/#25/#26 | merged/open | `planner_executor`/`single_agent`'s real tool execution — precedent for "a topology that actually calls something," not reused directly (see ADR-0008 for why `planner_executor` specifically doesn't fit). |

## Cross-references

- Source proposal: [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md) §"Update 2 (2026-09-13)" + scope-reduction note at top of section 3
- Governing ADR: [`../../docs/adr/0008-github-url-cli-and-deployment-target.md`](../../docs/adr/0008-github-url-cli-and-deployment-target.md)
- Scope-reduction decision record: [`../../docs/adr/0009-oss-helper-docs-only-scope.md`](../../docs/adr/0009-oss-helper-docs-only-scope.md)
- Prior phase: [`../07-adapter-pattern-pivot/index.md`](../07-adapter-pattern-pivot/index.md)
- Root phase index: [`../index.md`](../index.md)
