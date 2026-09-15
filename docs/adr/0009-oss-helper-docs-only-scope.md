# ADR-0009: oss-helper reduced to docs-only flow (GitHub issues/PRs source dropped)

## Status

Accepted (2026-09-15).

## Context

The original `agentops-oss-helper` flow (proposal §"Update 2 (2026-09-13)",
ADR-0008, phase 8) was designed to answer a user's question against two
evidence sources, both fed from the same public GitHub repository URL:

1. **The repo's own docs / README** — bulk-acquired via `git sparse-checkout`
   (or `codeload.github.com` tarball in a container without `git`) and
   indexed in-process by `WikiRagAdapter`.
2. **The repo's own issues and PRs** — acquired live from
   `GET https://api.github.com/search/issues?q=...` via `GitHubIssueAdapter`.

The two-source design was the whole point of phase 7's adapter pattern
(ADR-0007): `WikiRagAdapter` and `GitHubIssueAdapter` were both real
implementations, with the same Protocol shape, so `oss_triage` (or
whatever the flow was called) could mix-and-match by source kind.

In live testing against three real public repos on 2026-09-14, the docs
side worked end-to-end for `octocat/hello-world` and
`sh-ai-x/dev-harness-kit`. The GitHub-issues side failed in two of three
cases:

| Repo | Docs side | GitHub-issues side (anonymous) |
|---|---|---|
| `octocat/hello-world` | 5 wiki refs cited | 3 issue refs cited |
| `sh-ai-x/dev-harness-kit` (own repo, public) | 5 wiki refs cited | 0 issue refs + 422 |
| `facebook/react` | 5 wiki refs cited | 0 issue refs + 422 |

The two 422s came from GitHub's anonymous `/search/issues` endpoint
returning `{"message":"The listed users and repositories cannot be
searched either because the resources do not exist or you do not have
permission to view them."}` — not a permission failure, not a missing-repo
failure, but a spam-detection refusal: anonymous traffic against popular
or large repos is rate-limited harder than against small ones.

## Decision

Drop the `GitHubIssueAdapter` source from the `oss-helper` flow entirely.
The flagship flow is now **docs-only**: it parses the GitHub repo URL,
bulk-acquires the repo's own docs / README, builds a TF-IDF corpus via
`WikiRagAdapter`, and answers the user's question grounded in those
docs with citations.

The five adapters implemented under phase 7 — `WikiRagAdapter`,
`GitHubIssueAdapter`, `SecurityLogAdapter`, `IncidentLogAdapter`,
`TicketSystemAdapter` — remain in the codebase as a general-purpose
Adapter pattern demonstration (per phase 7 / ADR-0007). `oss-helper`
just does not use the GitHub-issues/PRs source.

## Rationale

The constraint that forced the change is GitHub's anonymous-search
rate-limit policy. The relevant facts:

1. **60 requests per hour per IP** for unauthenticated
   `/search/issues` traffic (the documented REST API anonymous quota).
2. **`/search/issues` is stricter for popular or large repos** even
   within that quota — it can return `422 Validation Failed` with
   message "The listed users and repositories cannot be searched..." for
   anonymous traffic against repos like `facebook/react`,
   `microsoft/typescript`, and any other repo that GitHub's spam
   detector flags.
3. **A demo that fails on the most common demo targets** (popular OSS
   repos) is not a demo. The `oss-helper` flow's value is showing that
   the Adapter pattern + bulk-doc acquisition work end-to-end on a real
   public repo. That value is preserved with the docs-only scope.
4. **Mitigations that would unblock the GitHub-issues source** all
   require either:
   - a user-supplied `AGENTOPS_GITHUB_TOKEN` (acceptable, but a setup
     step that breaks the "zero manual setup" exit criterion of
     `oss-helper`),
   - a different rate-limit-friendly third-party API (none exists for
     GitHub issue search at the volumes we want),
   - or per-repository pre-fetched caches (off-spec for a "paste a URL,
     ask a question, get an answer" demo).

   None of these are appropriate for the flagship flow's role.
5. **The Adapter pattern still pays its rent.** The remaining four
   adapters (`SecurityLogAdapter`, `IncidentLogAdapter`,
   `TicketSystemAdapter`, plus `WikiRagAdapter` as the only one wired
   in `oss-helper`) cover different real-world evidence-source patterns
   (RFC / IETF / syslog / ticket system), and the underlying Protocol
   shape from ADR-0007 is unchanged. Removing one of the five
   implementations doesn't invalidate the abstraction.

## Consequences

- **PR #36's `oss-helper` original implementation** (commits through
  `7db661f` on `feat/oss-helper-web`) is now superseded on this branch:
  the GitHub-issue source code is removed, the env-token plumbing is
  removed, and the rate-limit warning hook is removed. The branch tip is
  rewritten to commit `3d4f395` "refactor(oss-helper): drop GitHub
  issue/PR source -- docs-only flow" with that scope.
- **PR #40** (the original GitHub-feature branch rebase + docs-only
  reduction) was closed on 2026-09-15 because the prior rebase +
  cleanup + force-push had already produced a clean branch tip, and the
  intent of "open a new docs-only PR" is served by force-pushing to the
  same branch tip (no second PR needed). The closed PR retains the
  audit trail of the original (now-superseded) scope.
- **`oss-helper` runs anonymously.** Zero setup beyond `uv run uvicorn ...`
  and a pasted repo URL. The flow works on small public repos (`<10k`
  stars, modest issue count) without any further configuration. Larger
  repos may need a user-supplied `AGENTOPS_GITHUB_TOKEN` env var for any
  GitHub-side query we add in the future, but not for the current docs-
  only scope.
- **No new code in `oss-helper`'s hot path.** The previous rebase
  dropped `tests/test_actions_publish.py` (testing the now-removed ticket-
  execute endpoint that was PR #30's scope, not this PR's), the dead
  `_persist_tool_calls` function, the dead `_render_refs_section` for
  issues, the AGENTOPS_GITHUB_TOKEN warning banner, and the GitHub
  Issue/PR search qualifiers in the wiki prompt. Net diff is deletions
  against the previous branch tip.
- **Phase 8 (deployable MVP) status is unchanged** as a plan. The
  six operational fixes listed in `phases/08-deployable-mvp/index.md`
  (healthz, async runs, code-sha fail-closed, OTel redaction, 401/403
  distinction, per-principal spend cap) remain outstanding and unrelated
  to this scope-reduction decision.

## Related

- Proposal §"Update 2 (2026-09-13)" (`docs/proposals/agentops-workbench-proposal.md`)
  is the source proposal; the "Acquire the repo's docs" section
  (around line 277) describes the original split that this ADR
  supersedes for `oss-helper` only.
- ADR-0007 (`apps/agentops-workbench/docs/adr/0007-evidence-source-adapter-pattern.md`)
  established the multi-source design. This ADR-0009 does not reverse
  ADR-0007 — `oss-helper` is one flow that uses one source; the
  Adapter pattern and the other four implementations stay.
- ADR-0008 (`apps/agentops-workbench/docs/adr/0008-github-url-cli-and-deployment-target.md`)
  defined the GitHub-URL-CLI flow itself, including the GitHub-issues
  half. This ADR-0009 narrows the scope of that flow to docs-only;
  the rest of ADR-0008 (acquisition strategy, deployment target,
  rate-limit-warning UX) still applies.
