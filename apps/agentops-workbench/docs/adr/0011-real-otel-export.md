# ADR-0011: Real OpenTelemetry export for the wiki-chat path — opt-in SDK, off by default, redaction fixed regardless

## Status

Proposed (2026-09-17); revised same day to minimize footprint before
implementation begins (§Decision 1–2 below). Discharges the unmet Phase 5 exit
criterion recorded in
[`phases/05-delivery/index.md`](../../../../phases/05-delivery/index.md) §Exit
("traces do not expose synthetic secrets") and the proposal's Tech Stack
commitment to "OpenTelemetry only — correlate model calls, tools, state
transitions and failures". Scoped to the wiki-chat surface (`/v1/wiki/qa`,
`/v1/wiki/index-files`) and `observability/otel.py`. Does not modify any
retrieval adapter or the graph topology.

**Rollout is staged in two independent slices, deliberately not one PR:**

1. **The redaction fix (§Decision 4) ships alone, first.** No new dependency,
   no new setting, no behavior change for anyone — a pure correction to
   `REDACT_PATTERNS` inside the `Tracer` that already exists. It closes the
   credential leak described in §Context regardless of whether the rest of
   this ADR is ever built.
2. **The SDK + wiring (§Decision 1–3, 5–6) land second, and are a no-op by
   default.** Nobody who doesn't opt in gets a new dependency, a new file on
   disk, or any change in behavior.

## Context

`observability/otel.py` ships a hand-rolled span recorder: a `Span` dataclass,
a `Tracer` that appends to a list, a `redact()` pass over string/dict/list
attribute values, and `trace_to_jsonl()`. It is not OpenTelemetry. There is no
`opentelemetry-*` entry in `pyproject.toml` and `opentelemetry` appears zero
times in `uv.lock`.

Two spans exist, `wiki.search` (`graph/wiki_chat.py:146`) and
`wiki.qa.llm_chat` (`graph/wiki_chat.py:198`), both guarded by `if tracer:`.
The single live production call site — `api/server.py:1152-1154` — calls
`run_wiki_chat(adapter, body.corpus_id, body.query, thread_id, top_k=body.top_k)`
and never passes `tracer=`, so the parameter takes its `None` default
(`graph/wiki_chat.py:267`) and both guards always skip. **No span has ever been
created in the deployed path.** `trace_to_jsonl` is called only from
`tests/test_observability.py:92`. `Settings.runs_dir` (`settings.py:72-73`),
commented "Trace export (OTel spans per run)", is referenced nowhere in `src/`.

The observability that does ship is a different mechanism entirely: two
process-wide trailing-window recorders, `search_metrics` and
`groundedness_metrics` (`api/server.py:76-77`), surfaced at `/v1/wiki/metrics`.
Those give aggregates. They cannot answer "why was *this* turn slow" or "what
did *this* failed turn do before it failed" — which is the question a trace
exists to answer, and the one the proposal asked for.

Auditing the redaction pass before wiring an exporter surfaced two defects,
both verified by execution rather than inspection:

1. **A token leak from pattern ordering.** `redact("Authorization: Bearer abc123xyz")`
   returns `"authorization=[REDACTED] abc123xyz"`. The `authorization` pattern
   (`otel.py:22`) runs first, and its value class `[^\s,;}]+` consumes only the
   literal word `Bearer`, which then prevents the `bearer` pattern (`otel.py:25`)
   from matching. The credential survives.
2. **Three unredacted credential classes.** `AGENTOPS_JWT_SECRET=...`,
   `AGENTOPS_GITHUB_TOKEN=ghp_...`, and
   `postgresql://user:password@host/db` all pass through `redact()` unchanged.
   The DSN form is not hypothetical — it is literal text in
   `docker/docker-compose.yml:20` and `:44`. The proposal already warned that
   the list "must be extended *before* the flow ships, not after a token
   appears in an exported span"; that warning was never acted on.

Separately, `wiki.search` records the user's raw query as a span attribute
(`graph/wiki_chat.py:148`). Dormant today. Under a real exporter, private wiki
query text would leave the process — in tension with the corpus-privacy
property ADR-0010 §4 is built around.

## Decision

### 1. Real SDK is an optional extra — required for no one who doesn't opt in

`opentelemetry-api>=1.27,<2` and `opentelemetry-sdk>=1.27,<2` ship behind a new
extra, `otel = [...]`, following the exact precedent `dense` already set
(`pyproject.toml:39-42`) for an install-time opt-in. `Tracer` (§Decision 3)
imports them lazily and falls back to today's exact no-op recorder — the same
`Span`/list bookkeeping that exists now — when the extra isn't installed. This
is a deliberate reversal of the ADR's first draft, which made the SDK
required: both packages are pure Python with no compiled artifacts, so nothing
*forces* the extra, but "no side effect for anyone who hasn't asked for
tracing" is worth more than saving one `uv sync --extra otel` for operators who
actually want it.

The network exporter is a second, nested extra:
`otlp = ["opentelemetry-exporter-otlp-proto-http>=1.27,<2"]`, installed via
`uv sync --extra otel --extra otlp`. **HTTP/protobuf, not gRPC**: the gRPC
exporter pulls `grpcio`, a compiled wheel, into a CPU-only container targeting
an 8GB MacBook Air (ADR-0010 §Context). OTLP/HTTP on `:4318` is accepted by
`otel/opentelemetry-collector-contrib` unconfigured.

### 2. Exporter selection is configuration, mirroring `provider` — default `none`

Three new settings, `AGENTOPS_`-prefixed per `settings.py:15-21`:

- `trace_exporter ∈ {none, jsonl, otlp}`, **default `none`**
- `otlp_endpoint`, default `http://127.0.0.1:4318/v1/traces`
- `trace_content: bool`, default `False`

A `_guard_trace_exporter` validator rejects unknown names at startup, in the
same shape as `_guard_jwt_algorithm` (`settings.py:111-119`) and
`_guard_wiki_default_retrieval` (`settings.py:121-137`). Selecting `otlp`
without the extra installed raises from `_lifespan` with the `uv sync --extra otel --extra otlp`
command, mirroring the insecure-JWT refusal at `api/server.py:57-64`.

**`none` is the default, not `jsonl`.** This is the second reversal from the
first draft. With `none`, wiring `tracer=` into `run_wiki_chat` (§Decision 6)
is byte-for-byte behavior-neutral for every deployment that doesn't touch this
setting: no file appears under `runs_dir` on every QA turn, no
`.gitignore` entry is forced, nothing changes. `jsonl` is a new
dependency-free `JsonlFileSpanExporter` (writing
`{runs_dir}/{trace_id}.jsonl` in `trace_to_jsonl`'s existing one-span-per-line
shape) for the operator who explicitly wants it — it makes `runs_dir` do what
its comment has claimed since Phase 5, on request rather than by default.
`runs/` is added to `apps/agentops-workbench/.gitignore` in the same change
regardless of default, since the exporter can still be turned on.

The trade-off, stated plainly: Phase 5's exit criterion ("traces do not expose
synthetic secrets") is not demonstrated by *default runtime behavior* under
this revision — it is proven once, by the test suite, against the `jsonl`
exporter pointed at a `tmp_path` (§Decision 6, the D6 task). Correctness is
established at CI time; the cost of collecting a real trace is paid only by
whoever turns one on. §Decision 4's redaction fix applies unconditionally,
independent of which exporter (if any) is selected.

### 3. `Tracer` wraps a real `TracerProvider`; no sibling class

`Tracer`'s public surface — `start(name, parent=, attributes=)`,
`end(span, status=, extra=)`, `export()` — is preserved byte-compatibly, and
the four existing tests at `tests/test_observability.py:57-95` are the
regression lock. Internally it opens and closes real SDK spans.

A sibling adapter is rejected: `graph/wiki_chat.py` has eight call sites bound
to this shape, including the `LLMProviderError` classification at `:211-213`
that is the only thing making a failed turn diagnosable, and the object must
remain a handle passed through `config["configurable"]` rather than a
`ContextVar` — LangGraph may run nodes on a thread-pool worker, where an
implicitly-propagated context would not be visible. The explicit-handle
constraint is documented at `graph/wiki_chat.py:12-19` and is load-bearing.

One semantic change: `start()` with no explicit `parent` now attaches to the
tracer's innermost still-open span instead of becoming a root. This is what
makes `wiki.search` and `wiki.qa.llm_chat` children of the API-layer root
without touching either node.

### 4. Redaction is enforced at the exporter boundary and the list is extended

A `RedactingSpanExporter` decorator wraps the selected exporter, applying the
existing `redact()` to span attributes, event attributes, and
`status.description` before delegating. The exporter boundary is chosen because
it is the only chokepoint that also covers spans not created by our own
`Tracer`, and because it preserves today's semantics exactly — `Span.to_dict()`
already redacts at export, not at set time (`otel.py:58-61`).

`REDACT_PATTERNS` is corrected and extended, as a separate commit landing
before any exporter:

- `bearer` moves above `authorization`, fixing the leak in §Context item 1.
- `token` (`(?i)(token)\s*[:=]\s*[^\s,;}]+`) — the addition the proposal
  demanded for `AGENTOPS_GITHUB_TOKEN`.
- `secret` (`(?i)(secret)\s*[:=]\s*[^\s,;}]+`) — `AGENTOPS_JWT_SECRET`,
  `client_secret`.
- `github_token` (`gh[pousr]_[A-Za-z0-9]{16,}`) — the bare-value shape.
- `dsn` (`(?i)\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@]+@`) — connection-string
  userinfo.

`*_API_KEY`, `sk-`/`sk-ant-` values, and JWT-shaped tokens are already covered;
verified by execution, not assumed.

### 5. Content capture is a separate opt-in

`AGENTOPS_TRACE_CONTENT` defaults to `False`. When off, `wiki.search` records
`query_len` and `query_sha256_prefix` in place of `query`, and `wiki.index`
records counts in place of paths. Turning on tracing must not, by itself, start
shipping private wiki text off-box. This follows OTel's own
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` convention and the
deliberate double-opt-in idiom at `settings.py:83-92`.

### 6. The wiring lands in the API layer, and a test holds it there

Process-wide: the `TracerProvider`, `BatchSpanProcessor` and exporter are built
in `_lifespan` (`api/server.py:56-70`) and `force_flush()`/`shutdown()` on exit
— the only shutdown hook FastAPI offers, and `BatchSpanProcessor` drops its
queue without it. Resource attributes: `service.name`, `service.version` from
`api/server.py:70`, `agentops.code_sha` from `AGENTOPS_CODE_SHA` (`:190`).

Per-request: `wiki_qa` mints a `Tracer` with a fresh `uuid4().hex` trace id
adjacent to the existing `thread_id` mint (`:1114`), opens a `wiki.qa` root
span, wraps the API-thread search re-run (`:1136-1138`) in
`wiki.qa.search_resample`, **passes `tracer=tracer` into `run_wiki_chat`
(`:1152-1154`)**, and ends the root in the `finally` beside `adapter.close()`
(`:1166-1167`) with `error_kind` set from `LLMProviderError.kind` or
`UnknownCorpusError`.

One trace per turn, not per conversation: `thread_id` persists across turns
(`:1108-1112`) and would otherwise produce an unbounded trace. `thread_id`
rides as an attribute so turns stay correlatable.

`index_files` gains a `wiki.index` span around `index_uploaded_files`
(`:907-909`), reusing the values already computed for the log line at
`:914-921`. ADR-0010 §Consequences records index time rising to 10-30s for
dense modes and that this "must be surfaced... neither is acceptable as a
silent hang"; the span is the observability half of that obligation.

`tests/api/test_wiki_qa_tracing.py` asserts the exact four-span tree against an
`InMemorySpanExporter`. **The absence of such a test is why the omission at
`api/server.py:1152` survived.**

## Non-goals (explicitly decided, not overlooked)

- **`WikiRagAdapter` continues to reach the graph without an MCP hop, and this
  is correct.** The proposal's post-pivot diagram draws
  `ES --> A1[WikiRagAdapter]` as a direct edge and routes only
  `A0[DocsCorpusAdapter]` through the document and filesystem MCP servers; the
  proposal's own §Update-2 notes state that `SubprocessDocumentClient` is "a
  different code path that this flow does not use." Beyond intent, it is
  structurally required: `DocumentClient` (`mcp/__init__.py:26-31`) exposes
  three doc-id methods and a `DocRef` of `{doc_id, title, score}`, with no
  `read_evidence` and none of the AC3 provenance fields
  (`source_path`, `evidence_span`, `match_offsets`, `coverage`,
  `contributing_terms`, `mtime`, `obsidian_uri`) that `wiki_corpus.py:337-344`
  and the footnote-citation path in `graph/wiki_chat.py:82-93` are built on.
  No change is proposed or wanted.
- **Wiring `SubprocessDocumentClient` into `build_document_client` is
  deferred.** It is Phase 2's real unmet target and belongs to
  `DocsCorpusAdapter`, reachable only from the planner and single-agent
  topologies that ADR-0006 already records as non-shipping. Honest completion
  additionally requires making ADR-0002's "official Python SDK (`mcp==2.2.0`)"
  claim true — `mcp` appears nowhere in `pyproject.toml`, and
  `mcp/mcp_servers/document/server.py:159-176` is a hand-rolled JSON-RPC loop.
  Trigger for revisiting: either topology is promoted to a product surface, or
  ADR-0002 is reopened. One correction is worth landing regardless, as its own
  small change: the `mcp-document` service in
  `docker/docker-compose.yml:67-73` runs a stdio server with no stdin
  attached, so `for line in sys.stdin` (`server.py:161`) reads EOF and the
  container exits immediately. A long-lived standalone service for a stdio
  MCP server cannot work by construction; it should be deleted rather than
  left advertising a deployment that has never functioned.
- **No LangGraph auto-instrumentation.** Manual spans at the two node
  boundaries plus the API root are the whole requirement; an
  auto-instrumentor would add a dependency and emit spans nobody asked for.
- **No `/v1/wiki/metrics` change.** Traces and the trailing-window aggregates
  answer different questions and both stay.

## Consequences

- **A latent credential leak is closed before it could fire.**
  `Authorization: Bearer <non-JWT token>` currently survives `redact()`. It has
  never leaked because nothing is exported; shipping an exporter without the
  ordering fix would have made it a real disclosure on the first trace.
- **Three credential classes introduced since Phase 5 are now covered.**
  `AGENTOPS_JWT_SECRET`, `AGENTOPS_GITHUB_TOKEN`, and `AGENTOPS_DATABASE_URL`'s
  userinfo. The proposal's "before, not after" instruction is honoured.
- **Default behavior is unchanged for every deployment that doesn't opt in.**
  `trace_exporter=none` by default, and the SDK itself is behind the `otel`
  extra — no new dependency, no new file on disk, no new setting an operator
  has to think about, unless they explicitly install the extra and flip the
  setting. Choosing `jsonl` writes roughly 2KB per QA turn to `runs_dir`;
  `runs/` gains a `.gitignore` entry regardless, since the exporter can still
  be turned on.
- **`opentelemetry-api`/`-sdk` are opt-in, not required.** Pure Python, no
  compiled deps, no network at import — nothing *forced* this to be an extra —
  but the default install's `uv.lock` and CI install time are completely
  unaffected. `grpcio` is specifically avoided even for the opt-in path.
- **CI stays offline and skip-free.** No `skipif`/`importorskip` is added.
  Every tracing test runs against `InMemorySpanExporter` or `tmp_path` JSONL;
  the `otlp` branch is covered by testing its *startup refusal* when the extra
  is absent, never by opening a socket. This matches ADR-0010 §Consequences'
  "CI stays offline and skip-free" commitment.
- **Span parenting semantics change for any future caller.** `start()` without
  an explicit `parent` now nests under the innermost open span. All four
  existing tests remain valid — the only multi-span test ends its first span
  before starting the second — but a future caller expecting an implicit root
  must pass `parent=None` deliberately.
- **`wiki.search`'s `query` attribute is gated off by default.** An operator
  who wants query text in traces sets `AGENTOPS_TRACE_CONTENT=1` and thereby
  accepts that private wiki text leaves the process.
- **`runs_dir` stops being dead configuration.** It has been declared and
  unreferenced since Phase 5.
- **The duplicate search per QA turn becomes visible.** `api/server.py:1125-1133`
  admits in a comment that the handler re-runs `search_with_timing` purely for
  metrics. Under `wiki.qa.search_resample` that cost shows up in every trace,
  which is the precondition for deciding whether to remove it.
- **Phase 5's exit criterion becomes verifiable.** A test drives a turn carrying
  a synthetic secret and asserts its absence from every byte of exported
  JSONL — an artifact, replacing an unfalsifiable claim.

## Alternatives considered

**A. Keep the hand-rolled `Tracer` and just call it from `server.py`.** The
smallest possible diff; spans would finally exist. *Rejected*: it does not
satisfy "OpenTelemetry only", it cannot feed a collector, Jaeger, or any
backend, and it leaves the project claiming a standard it does not implement.
The wiring gap is the smaller half of the problem.

**B. Replace `Tracer` outright with OTel's native context-manager API.** The
most idiomatic end state. *Rejected*: it rewrites both `wiki_chat` nodes
including the `LLMProviderError` classification at `:211-213`, discards the
four existing regression tests, and — decisively — OTel's implicit `ContextVar`
propagation is not reliable across LangGraph's node execution, which may run on
a thread-pool worker. The explicit-handle-through-`configurable` constraint at
`graph/wiki_chat.py:12-19` is not incidental.

**C. gRPC OTLP exporter (`opentelemetry-exporter-otlp-proto-grpc`).** The more
common default in OTel documentation. *Rejected*: `grpcio` is a compiled wheel
and the most frequent `uv sync` failure on arm64 and Alpine. The deployment
target is a CPU-only container on an 8GB laptop. HTTP/protobuf reaches the same
collector on `:4318`.

**D. `ConsoleSpanExporter` as the non-OTLP default.** Zero new code.
*Rejected*: console output is not an artifact, cannot be asserted against in
the Phase 5 secret-absence test without capturing stdout, and would interleave
with the structured `log.info` lines at `api/server.py:916-921` and `:1181-1187`.

**E. Redact at attribute-set time inside `Tracer.start`/`end` instead of at the
exporter.** Slightly stronger — secrets never enter process memory in a span.
*Rejected*: it only covers spans our own `Tracer` creates, leaving any other
instrumentation unprotected, and it diverges from the current semantics where
`Span.to_dict()` redacts at export, not at set time. The exporter decorator is
the single chokepoint.

**F. `OTEL_*` standard environment variables instead of `AGENTOPS_TRACE_*`.**
Interoperable with the wider OTel ecosystem. *Rejected*: every other runtime
knob on this project is an `AGENTOPS_`-prefixed `Settings` field with a startup
validator (`settings.py:15-21`, `:111-149`), and that convention buys
fail-at-startup on a typo, which bare env-var reads do not. `OTEL_*` variables
the SDK reads natively still work as a lower-precedence layer; they are simply
not the documented surface.

**G. Trace the `/v1/runs` topology path in the same change.** Broader coverage.
*Rejected as a substitute*: `/v1/wiki/*` is this project's live surface and the
one with an existing, dormant span vocabulary. Extending to `run_topology` is
orthogonal and can reuse everything this ADR builds.

## References

- `src/agentops_workbench/observability/otel.py` — `REDACT_PATTERNS` (`:19-30`),
  `redact` (`:33-44`), `Span.to_dict` (`:58-61`), `Tracer` (`:64-100`),
  `trace_to_jsonl` (`:109-111`).
- `src/agentops_workbench/graph/wiki_chat.py` — the two existing spans
  (`:146-159`, `:198-216`), the `configurable`-not-state constraint (`:12-19`),
  the `tracer` parameter (`:267`, `:281`).
- `src/agentops_workbench/api/server.py` — `_lifespan` (`:56-70`), `index_files`
  (`:885-927`), `wiki_qa` (`:1095-1199`), and the untraced call at
  `:1152-1154`.
- `src/agentops_workbench/settings.py` — `AGENTOPS_` prefix (`:15-21`), the dead
  `runs_dir` (`:72-73`), the double-opt-in idiom (`:83-92`), the validator shape
  (`:111-149`).
- `src/agentops_workbench/mcp/__init__.py` — `DocumentClient` Protocol
  (`:26-31`), `build_document_client` (`:72-99`) — the Non-goals evidence.
- `docker/docker-compose.yml:67-73` — the non-functional `mcp-document` service.
- [ADR-0002](0002-mcp-boundaries.md) — the "official Python SDK" claim this ADR
  declines to make true, and names as the trigger for revisiting.
- [ADR-0003](0003-provider-abstraction.md) — the config-driven-selection idiom
  the exporter setting mirrors.
- [ADR-0007](0007-evidence-source-adapter-pattern.md) — §4 "Unknown names fail
  at startup", applied to `trace_exporter`.
- [ADR-0010](0010-dense-retrieval-and-reranking.md) — the offline/skip-free CI
  commitment and the index-latency obligation `wiki.index` answers.
- `phases/05-delivery/index.md:8,14` — the exit criterion this ADR discharges.
- `docs/proposals/agentops-workbench-proposal.md:811` (Tracing row), `:618-622`
  (the redaction-list warning), `:845-873` (post-pivot diagram + prose),
  `:607-612` (the `SubprocessDocumentClient` separation), `:985-992` (Phase 5).
