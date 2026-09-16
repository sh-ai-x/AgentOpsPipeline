# 09-wiki-browser-picker

> Phase 9 — browser-native wiki directory picker, wired to the existing
> `WikiRagAdapter` retrieval layer, with provenance + groundedness
> indicators surfaced in the web UI.

- **Proposal section:** [`../../docs/proposals/agentops-workbench-proposal.md`](../../docs/proposals/agentops-workbench-proposal.md)
  §"Update 3 (2026-09-16): Browser-native wiki picker"
- **Exit criteria** (three, all independently checkable):
  1. **AC1 — directory picker.** A reviewer opens the web UI in a
     Chromium-based browser, clicks "Pick directory", the OS native
     picker appears with the permission prompt. On approval the picked
     directory's `.md` files are accessible to the agent (zero manual
     upload, zero manual file copying, zero filesystem mounts by the
     server).
  2. **AC2 — LangGraph wire-up.** The picked corpus is indexed by the
     existing `WikiRagAdapter` (TF-IDF + cosine), and a search query
     against it routes through the same `build_document_client`
     factory the `planner_executor` and `single_agent` topologies
     already use. No new retrieval algorithm, no new graph nodes —
     only a new corpus-id carrier.
  3. **AC3 — trust indicators.** Every search result carries
     `source_path` (real on-disk path the user picked), `evidence_span`
     (the substring containing the matching terms, with `<mark>`-ready
     offsets), `score` (cosine), `coverage` (matched query terms /
     total query terms, 0..1), `contributing_terms` (top terms that
     pushed the score), and `mtime` (file modification time as ISO).
     QA mode additionally returns per-sentence `groundedness` =
     token-set overlap with the cited `[ref_id]` evidence.

## Why this phase exists

The existing wiki integration assumes the operator sets
`AGENTOPS_WIKI_DIR` to a path on the server's filesystem. That works
for server-side deployments but is a hard blocker for two real
audiences:

1. **Reviewers running locally** — they have an Obsidian vault or a
   `~/dev/mywiki` directory on their own laptop. Asking them to copy
   the corpus into a docker-mounted volume breaks the "open the URL,
   try it" flow that ADR-0008 set up.
2. **Browser-only deployments (Vercel, Cloudflare Pages)** — no
   filesystem at all. The only way for these to be useful for
   personal-wiki workflows is for the **browser** to supply the
   files via the File System Access API.

Phase 9 closes that gap without rewriting the retrieval layer: the
existing `WikiRagAdapter` becomes corpus-scoped (keyed by a server-
issued `corpus_id`), the browser reads files via the OS picker and
hands the bytes to the server, the server indexes and serves the
same way it already does.

## Deliverables

1. **`wiki_corpus.py` registry** — module-level
   `WikiCorpusRegistry` keyed by `corpus_id` (UUID4). Stores the
   adapter + file mtimes; eviction via LRU at a configurable cap
   (default 16 active corpora, ~200 MB TF-IDF footprint each).
2. **`POST /v1/wiki/index-files`** — multipart upload endpoint.
   Browser sends `[{path, content}]` for every `.md` file under
   the picked directory; server writes to a temp dir, calls
   `collect_wiki_files`, returns `{corpus_id, doc_count, domains}`.
3. **`GET /v1/wiki/search?corpus_id=&q=`** — scoped search. Returns
   the existing `EvidenceRef` shape **plus** `source_path`,
   `evidence_span` (with match-offset list), `coverage`,
   `contributing_terms`, `mtime`.
4. **`POST /v1/wiki/qa`** — search → LLM answer → per-sentence
   groundedness. Prompt asks the LLM to ground every claim with
   `[ref_id]`; the response is sentence-split, each `[ref_id]` is
   resolved to its evidence text, and `groundedness` is the
   token-set Jaccard overlap between the sentence and the union
   of its cited evidence.
5. **`groundedness.py`** — pure-Python tokenizer + Jaccard +
   sentence splitter. No NLI model (intentional — keeps the
   dependency surface small and the scorer deterministic).
6. **Frontend updates (`web/app/page.tsx`)** — `Pick directory`
   button using `window.showDirectoryPicker()`. Recursive walk
   client-side, junk-skip mirroring the server's `SKIP_DIR_NAMES`,
   file count summary, then POST + result rendering with all five
   trust indicators + per-sentence groundedness badges.

## Explicitly not in this phase

- Persistent corpus storage across server restarts. `corpus_id` is
  process-local; the browser must re-pick after each restart.
  (Persisting would mean writing user files to the server's disk —
  a privacy regression that's worse than the friction.)
- File System Access API polyfill for Safari/Firefox. Both browsers
  ship a separate, less capable picker (`<input type="file" webkitdirectory>`)
  which loses subdirectory walk. We'll accept that limitation
  explicitly rather than ship two code paths.
- NLI-based groundedness (TRUE / FACTS-Ground / AttrEval). The
  token-Jaccard scorer is a documented proxy, not a calibrated
  metric — it's enough to surface *which sentences look
  unsupported* without claiming calibrated hallucination rates.

## Build plan (TDD order)

1. **Test first**: `tests/test_wiki_corpus.py` — registry CRUD,
   LRU eviction, file-index round-trip, search returns the
   expected provenance fields.
2. **Test first**: `tests/test_groundedness.py` — token Jaccard
   against hand-built cases (zero overlap → 0.0, identical →
   1.0, mixed citations → averaged).
3. **Test first**: `tests/test_api_wiki.py` — endpoints with
   `TestClient`, multipart upload, JWT auth gate.
4. **Implement**: `wiki_corpus.py`, `groundedness.py`, the three
   endpoints, then frontend.
5. **Verify**: full pytest suite green; manual smoke (real
   `hermes-wiki-super` upload via the dev server) returns hits
   with all five trust indicators.

Core tests that must pass:

- `tests/test_wiki_corpus.py::test_index_files_returns_corpus_id`
- `tests/test_wiki_corpus.py::test_search_returns_provenance_fields`
- `tests/test_wiki_corpus.py::test_lru_eviction_when_cap_exceeded`
- `tests/test_groundedness.py::test_jaccard_identical_is_one`
- `tests/test_groundedness.py::test_per_sentence_groundedness_with_citations`
- `tests/test_api_wiki.py::test_index_files_requires_jwt`
- `tests/test_api_wiki.py::test_search_after_index_returns_results`
- `tests/test_api_wiki.py::test_qa_returns_per_sentence_groundedness`
- The existing 256-test regression suite stays green.
