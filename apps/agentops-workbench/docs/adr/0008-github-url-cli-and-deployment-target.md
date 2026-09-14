# ADR-0008: GitHub-URL CLI flow scope + deployment target

## Status

Accepted (2026-09-13).

## Context

ADR-0007 generalized the evidence-retrieval seam into an
`EvidenceSourceAdapter` Protocol and PR #34 shipped five real
implementations (`WikiRagAdapter`, `GitHubIssueAdapter`,
`SecurityLogAdapter`, `IncidentLogAdapter`, `TicketSystemAdapter`), none
wired into `graph/**`. That left two open questions this ADR settles:
which single, concretely demoable flow proves the pattern (rather than
presenting five abstract adapters and asking a reviewer to pick one), and
where the backend actually runs — there is a local-only
`docker/docker-compose.yml` and no deployment target at all.

Two facts, discovered while specifying the flow rather than assumed going
in, force most of the decisions below:

- **`WikiRagAdapter.__init__` builds a corpus-wide document-frequency
  table (`self._df`, `self._n_docs`) before any query runs.** IDF is a
  property of the whole corpus by definition. A per-query GitHub Contents
  API fetch cannot produce it — that would be scoring against an IDF
  table of one document. Bulk acquisition of the docs corpus is a
  constraint of the algorithm already shipped, not a style preference.
- **`WikiRagAdapter` globs `*.md` non-recursively.** A real repository's
  docs are nested (`docs/guide/install.md`). Left unhandled, the adapter
  silently sees none of them.
- **PR #34's shipped `EvidenceRef` dropped the `uri` field this ADR's
  predecessor (ADR-0007 §2) specified**, and `read_evidence` takes
  `ref_id`, not `evidence_id`. Recorded here as a known divergence rather
  than quietly reconciled: a citation therefore has no self-describing
  link, and whatever renders one has to supply it.

## Decision

### The flagship flow

```
agentops-oss-helper <github-repo-url> [--issue N | --question "..."]
```

Paste a public GitHub repository URL, optionally with an issue number or
a free-text question. The tool works off that repository's own Issues/PRs
and its own docs/README, and produces a grounded triage or answer draft
with a citation behind every claim, or an explicit refusal when the
evidence does not support one. **Local-first**: no hosted multi-tenant
service backs this flow — a maintainer clones this repo, sets one token
env var, and points the CLI at their own repository. The deployed API
(below) is a second, independent surface proving the backend deploys; it
is not where this flow is meant to be consumed.

**Acquisition is split, forced by the two facts above, not chosen:**
Issues/PRs are not in the git tree at all — they exist only through the
API, are mutable, and are queried rather than enumerated — so
`GitHubIssueAdapter` (already `httpx`-based) is the only path. Docs are
acquired in bulk: `git clone --depth 1 --filter=blob:none --sparse` then
`git sparse-checkout set` the allowlisted doc roots when `git` is
available locally; a `codeload.github.com/<owner>/<repo>/tar.gz/<ref>`
fetch when it isn't (a container image with no `git` binary). Either way,
matched `*.md`/`*.mdx` files are **flattened** into one temp directory
with path separators encoded into the stem
(`docs__guide__install.md`), keeping a stem → `(repo path, commit sha)`
map — this is also how a citation gets a real URL
(`https://github.com/<owner>/<repo>/blob/<sha>/<path>`) despite
`EvidenceRef` having no `uri` field. A default cap (order of a few
hundred markdown files) makes a monorepo fail loudly with a named
`--max-docs` override, instead of wedging on an in-process linear-scan
TF-IDF index.

**A new topology, not `planner_executor`.** `planner_executor` cannot
host this flow as-is: it takes exactly one `document_client`, not two
adapters; its `_execute_step` calls `search_docs`/`read_document` by
name, which PR #34's adapters don't implement (they implement
`search_evidence`/`read_evidence`); `get_issue` raises
`NotImplementedError` by design (no backend existed before this ADR); and
`run_topology(name, adapter, task)` has no parameter to forward a client
at all. A new topology, `oss_triage` (`graph_version="oss-triage-v1"`),
takes both adapters explicitly. Four nodes, one LLM call: gather (both
adapters' top-k), classify (evidence sufficient / insufficient), answer,
refuse.

**Scores are never merged across adapters.** GitHub's search relevance
score is unbounded; `WikiRagAdapter`'s cosine similarity is bounded in
`[0, 1]`. Top-k per adapter, presented as separate labelled evidence
blocks — never sorted together as if they were one ranked list.

### Deployment target

**Fly.io**, one container, **SQLite on a persistent volume instead of
Postgres** — this workload is one writer with a kilobyte-scale dataset at
demo traffic, and Postgres's operational cost (a managed instance, or a
second container) buys nothing at that scale. Scale-to-zero matches
near-zero demo traffic between reviewer visits. Estimated **~$2–6/month**,
dominated by the machine + volume; LLM spend is separately metered and
measured in cents (`experiments/held-out-v1/manifest.json`:
$0.0124 / 24 runs). Railway is the named runner-up (same shape, slightly
different pricing curve); a bare VPS was rejected for the ops burden a
portfolio project shouldn't be carrying, and free tiers that sleep after
inactivity were rejected because a cold-started demo in front of a
reviewer is a worse failure mode than a small monthly cost.

**Backend/frontend split, made falsifiable, not just described:**
`streamlit` moves out of `[project.dependencies]` into an optional `ui`
extra (`pyproject.toml`) — the acceptance test for "the backend doesn't
need the frontend" is that the deploy image builds and the smoke test
passes with Streamlit absent from the environment entirely, not merely
that the API happens to work if you don't launch the UI process.

## Consequences

- **Operational gaps this scoping surfaced, each anchored to code, that
  the deploy target does not paper over:**
  - No `/healthz` route exists — the only unauthenticated route is
    `/_debug/retrieve`, which builds a retriever on every call and is not
    a health check.
  - `create_run` (`api/server.py`) executes the graph synchronously
    in-request. A deployed target needs `202 Accepted` + a poll endpoint,
    not a bigger timeout.
  - `AGENTOPS_CODE_SHA` defaults to the literal string `"dev-sha"` — every
    `Run` row persisted without that env var set has fake provenance.
  - The OTel redaction list (`observability/otel.py`) does not include
    `token` — a `GITHUB_TOKEN`-bearing header would not be redacted from
    a trace by the existing rule set.
  - `_raise_for_status`-style error handling conflates HTTP 401 and 403
    in at least one path, so a caller cannot distinguish "bad
    credentials" from "rate-limited."
  - A public, LLM-calling endpoint currently has no per-principal spend
    cap — `SpendCeiling` exists for the held-out experiment runner, not
    for `/v1/runs`.
  These are not blocking this ADR's acceptance; they are the concrete,
  named punch list a deploy PR must close, replacing "make it
  production-ready" with six checkable items.
- `EvidenceRef`'s missing `uri` field (the divergence from ADR-0007 noted
  above) is closed specifically for the Wiki side by the stem→(path,sha)
  map this ADR requires; `GitHubIssueAdapter` already has a natural URL
  (`https://github.com/<owner>/<repo>/issues/<number>`). A future pass
  should decide whether to add `uri` back to `EvidenceRef` itself so
  every adapter carries its own citation link rather than each caller
  reconstructing one — out of scope here.
- No subprocess cold-start cost applies to this flow: PR #34's adapters
  run in-process. The subprocess lifecycle question belongs to PR #29's
  `SubprocessDocumentClient`, a different, already-separately-scoped path.
- Out of scope for this iteration, unchanged from ADR-0007 plus: no
  multi-tenant authentication for the CLI flow, no write-back of any kind
  to the target repository (no comments, labels, or PRs — read-only
  against GitHub), no private-repository support in the flagship flow,
  and no autoscaling, multi-region, or Kubernetes story.
