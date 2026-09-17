# ADR-0010: Dense retrieval, hybrid fusion and CPU reranking for WikiRagAdapter — without pgvector

## Status

Proposed (2026-09-17). Discharges the obligation
[ADR-0007](0007-evidence-source-adapter-pattern.md) §Migration-path step 5 created:
"`WikiRagAdapter`. Largest: embeddings, vector index, its own recall gold labels.
Carries the pgvector reversal, which needs its own ADR." This is that ADR.
Scoped to `WikiRagAdapter`; no other adapter changes. Adds a second per-source
dataset instance under [ADR-0004](0004-dataset-separation.md)'s convention.

## Context

`WikiRagAdapter` ships two lexical retrieval modes, `retrieval="tfidf"` (default)
and `retrieval="bm25"`, both pure Python. Its module docstring names dense
retrieval a "deliberate non-goal" on two grounds: a local embedding model
"breaks the dependency-light design", or a provider embeddings endpoint costs
"network + cost per search". Both grounds were accurate when written, and the
second one still is. The first is not: an int8-quantized 384-dim ONNX
sentence encoder is 67MB on disk and runs a batch of chunks in single-digit
seconds on a CPU laptop, with no GPU and no `torch`.

Three concrete retrieval weaknesses motivate changing this, all of which the
lexical modes share by construction:

1. **Whole-file indexing.** `__init__` tokenizes each `.md` file in its
   entirety. A 4000-word note about six topics is one vector. BM25's length
   normalization softens this; it does not fix it. The retrieved unit is also
   the *cited* unit — `graph/wiki_chat.py` feeds `read_evidence(ref_id,
   limit=2000)` into the prompt, i.e. the first 2000 characters of a whole
   file, which may not be the part that matched.
2. **Zero vocabulary overlap ⇒ zero score.** Both modes score only terms the
   query literally contains. A note titled "Resuming interrupted runs" is
   unreachable from "how do I restart after a crash". This is the failure
   class dense retrieval exists for, and it is invisible in the current
   metrics because the project has no retrieval-quality gold labels at all —
   only answer-level metrics (ROUGE-L F1, Citation Precision/Recall,
   Faithfulness in `groundedness.py`).
3. **No ranking beyond first-stage score.** Nothing re-examines the top-k
   jointly with the query.

ADR-0007 also warned that "`retrieval_recall@k` needs gold labels over wiki
content before any number from it means anything." No such labels existed. So
this ADR is not allowed to claim an improvement; it is required to build the
instrument that could measure one, and it must measure both raw retrieval
quality and how each mode moves the answer-level groundedness dashboard
(Citation Precision, Citation Recall, ROUGE-L F1, Faithfulness) that already
ships in the web UI.

Hard deployment constraint: the target machine is a MacBook Air, 8GB RAM,
no usable GPU, alongside a FastAPI worker and a Next.js dev server. Budget for
loaded model weights plus inference runtime: ~200-250MB.

## Decision

### 1. Three new retrieval modes, strictly additive

`_VALID_RETRIEVAL_MODES` becomes
`{"tfidf", "bm25", "dense", "hybrid", "hybrid_rerank"}`. A new
`_LEXICAL_MODES = frozenset({"tfidf", "bm25"})` marks the existing two.

- `dense` — chunk-level cosine similarity over 384-dim embeddings.
- `hybrid` — chunk-level BM25 ∪ chunk-level dense, fused by Reciprocal Rank
  Fusion (Cormack, Clarke & Büttcher 2009), `k=60`.
- `hybrid_rerank` — `hybrid`'s top 20 candidates re-scored by a cross-encoder,
  truncated to `top_k`.

`tfidf` and `bm25` remain the only modes that exist by default and remain
byte-identical in behaviour. This is enforced, not asserted: a committed
golden-score fixture pins exact float scores for both modes over a fixture
corpus, and a test asserts `"fastembed" not in sys.modules` after constructing
and querying a lexical adapter. Heavy imports live inside the non-lexical
branches only, so a deployment that never selects a new mode pays zero import
cost, zero download, zero RSS.

### 2. Chunking is a prerequisite, and it is pure string ops

A new leaf module `chunking.py`: markdown-header-aware segmentation
(ATX `#`..`######`, correctly ignoring headings inside fenced ``` / ~~~
blocks), then a recursive paragraph→sentence→hard-slice fallback for sections
over `_CHUNK_MAX_CHARS = 1200` (~300 tokens, comfortably inside bge-small's
512-token truncation and the cross-encoder's 512-token pair limit), with
`_CHUNK_OVERLAP_CHARS = 150`. No ML, no new dependency; the sentence splitter
is the one `wiki_corpus.split_sentences` already ships, relocated to a leaf
`text_utils.py` and re-exported.

Chunks are built **only** for non-lexical modes. `self._files` (whole-file) is
untouched and still always built. Chunk ref_ids are `f"{parent_ref_id}#c{n}"`;
`read_evidence` resolves `self._files` first (unchanged path) and falls back to
the chunk table. `#` is deliberately outside `wiki_corpus._CITATION_RE`'s
character class, and no HTTP route carries a ref_id in a URL path, so the new
id shape cannot collide with the citation or routing surfaces.

### 3. Local ONNX models, gated behind an optional extra

`[project.optional-dependencies] dense = ["fastembed>=0.7,<1.0"]`.
Pinned models: `BAAI/bge-small-en-v1.5` (embeddings) and
`Xenova/ms-marco-MiniLM-L-6-v2` (cross-encoder). Both are ONNX; `fastembed`
depends on `onnxruntime`, never `torch`. Model objects are process-global
singletons keyed by model name — **not** per-adapter — because
`wiki_corpus.DEFAULT_CAP` keeps up to 16 corpora alive simultaneously.

The "dependency-light" property is preserved where it was actually load-bearing:
the *default* install gains nothing, and the lexical scorers remain pure Python.
Opting into `[dense]` buys `onnxruntime`, `tokenizers`, `huggingface-hub` and
`numpy` (already present transitively in `uv.lock`), and `numpy` is imported
lazily inside the dense branch only.

### 4. pgvector is explicitly declined

ADR-0007 flagged that this work "pulls pgvector back into scope". It does not.
A vault capped at `MAX_WIKI_DOCS = 4096` files yields at most ~20k chunks
(a new `MAX_WIKI_CHUNKS = 20000` cap enforces this with the same loud
`MCPError("unsupported_capability")` semantics `MAX_WIKI_DOCS` already uses).
20k × 384 × 4 bytes = 30MB as one float32 matrix, and an exact brute-force
matrix-vector product over it is ~10ms — faster than any ANN index's network
round-trip. Introducing pgvector would add a required service to a tool whose
central privacy property is that nothing is persisted to server disk beyond
the corpus lifetime. **The proposal's pgvector deferral therefore stands; it is
not reversed.** If a corpus ever exceeds `MAX_WIKI_CHUNKS`, that is the trigger
to revisit, in its own ADR.

### 5. Retrieval quality gets its own frozen dataset and its own harness, on two axes

Per ADR-0007 ("Dataset splits are per source... Numbers do not pool across
sources"), a new `fixtures/wiki_eval/` instance of ADR-0004's convention: a
committed ~28-note corpus, plus 30 labelled queries split **18 dev / 6 val /
6 held-out** over six families — `single_hop`, `multi_hop`, `paraphrase`,
`synonym`, `acronym`, `no_answer` — with `fixtures/wiki_eval/HELD_OUT_SHA256.txt`
frozen the same way `fixtures/cases/HELD_OUT_SHA256.txt` is.

The family distribution is load-bearing, not decoration: a gold set made only
of keyword-overlap queries would make the lexical baseline win and would
"prove" dense retrieval useless. `paraphrase` / `synonym` / `acronym` are where
a dense leg is supposed to pay for itself, and `no_answer` is where it is
supposed to be dangerous — a dense index returns its nearest neighbour for
gibberish, which would silently defeat `wiki_chat`'s refusal path. A dense
cosine floor (`_DENSE_MIN_COSINE`) is tuned on dev/val to preserve the
"no relevant evidence → empty result" contract the lexical modes get for free.

**Axis 1 — retrieval-level.** `benchmark/retrieval_metrics.py` (new, pure
Python): Recall@k, Precision@k, MRR, nDCG@k with graded relevance, Hit-rate@k,
and a secondary chunk-level Precision@k. `benchmark/scorers.py` is **not
modified** — its `retrieval_recall_at_k` is typed to `BenchmarkCase` and
belongs to the answer-level 30-case benchmark; only its empty-gold→1.0
convention is reused. Chunk hits collapse to their parent file before
file-level metrics so all five modes are scored on the same unit.

**Axis 2 — answer-level, against the shipped groundedness dashboard.** The
four metrics `groundedness.py` already computes (Faithfulness, Citation
Precision, Citation Recall, ROUGE-L F1) are all deterministic, offline, and
score the *answer* against *whatever was retrieved* — they cannot by
themselves say a retrieval mode is better, only whether the model stayed
consistent with what it was given. Two gold-grounded additions close that
gap: `answer_citation_correctness@gold` (does a cited hit's parent match the
query's `relevant_refs`) and `answer_contains_gold` (does the answer contain a
gold phrase, independent of what was retrieved). Investigation during this
ADR's own review found Citation Precision/Recall track prompt compliance more
than retrieval quality (nearly every emitted footnote resolves regardless of
mode, since the prompt only offers `1..k`); Faithfulness is the more sensitive
of the four shipped metrics, and ROUGE-L F1 is confounded by evidence length
(chunk modes return denser, shorter evidence than whole-file modes), so it is
reported alongside a mean-`evidence_tokens` control column, never alone.

A runner, `experiments/retrieval_ab.py` (`--phase {retrieval,answers,both}`,
CLI: `scripts/eval_retrieval.py`), prints one row per mode per axis plus a
per-family breakdown and a per-query win/loss diff versus the `bm25` baseline,
and writes `experiments/retrieval-ab-v1/{manifest.json,per_query.jsonl,
report.md}` — the same artifact shape as `experiments/held-out-v1/`. The
answer-level phase reuses `fixtures/wiki_eval/dev` (not the 30-case
`fixtures/cases/`, whose `source_refs` carry no gold for this corpus and whose
benchmark scores a tool-using agent this graph is not), mints a fresh
`thread_id` per (mode, query) turn to prevent conversation-history leakage
between queries, runs under a `SpendCeiling`, and is gated to CI only via a
scripted-answer fake double (the shipped `local-fake` provider's regex does
not match `wiki_chat`'s prompt shape and degenerates to all-zero metrics for
every mode — documented, not silently relied on). Tuning happens on dev+val
only; held-out is read once and only its numbers are quoted anywhere.

### 6. Selection stays index-time configuration

`IndexFilesBody.retrieval`'s `Literal` widens to the five names (invalid values
keep getting a 422 before any adapter is built),
`AGENTOPS_WIKI_DEFAULT_RETRIEVAL` gains a startup validator rejecting unknown
modes — mirroring ADR-0007 §4's "Unknown names fail at startup" — and the web
picker gains three options plus an echo of the resolved mode so the live
groundedness dashboard can attribute its numbers to the mode that produced
them. Retrieval remains fixed per corpus at index time, as today. The
dashboard itself does **not** gain a per-mode comparison view (see
Consequences) — the A/B comparison stays a batch, offline artifact.

## Consequences

- **`score` stops meaning one thing.** `tfidf` emits cosine in 0..1, `bm25`
  emits an unbounded Okapi sum, `hybrid` emits an RRF score in ~0.016..0.033,
  `hybrid_rerank` emits a sigmoid of a cross-encoder logit in 0..1. The web
  UI's score tooltip and `groundednessColor` thresholds must become mode-aware.
- **Index time goes from ~200ms to ~10-30s** for a few-hundred-note vault
  (embedding is the cost), and first-ever use downloads ~150MB from the
  HuggingFace hub into `~/.cache/huggingface`. Both must be surfaced in the UI;
  neither is acceptable as a silent hang.
- **The 16-corpus LRU becomes a memory hazard.** 16 dense corpora × 30MB
  matrices is 480MB even with singleton models. Mitigated by singletons plus
  `MAX_WIKI_CHUNKS`; lowering `DEFAULT_CAP` when a dense mode is active is
  noted as a follow-up, not done here.
- **`hybrid_rerank` sits at the edge of the RAM budget.** bge-small ≈ 90-120MB
  RSS with a live ORT session, ms-marco-MiniLM-L-6 ≈ 110-140MB, onnxruntime
  itself ≈ 40-60MB. `dense`/`hybrid` land ~150-180MB (inside budget);
  `hybrid_rerank` lands ~250-320MB (at or slightly over). The reranker is
  therefore constructed lazily on first rerank call, not at adapter
  construction, so merely *offering* the mode costs nothing.
- **CI stays offline and skip-free.** The suite contains zero
  `skipif`/`importorskip`. It stays that way: the adapter takes injectable
  `embedder` / `reranker` seams, unit tests supply deterministic in-repo fakes,
  and the harness runs end-to-end under `--embedder fake` / `--llm
  fake-citing`. The real-model path's L1 verification artifact is the
  committed `experiments/retrieval-ab-v1/` report from an operator run, exactly
  as `experiments/held-out-v1/` serves that role today.
- **Citation Precision/Recall are found to be prompt-compliance metrics, not
  retrieval-quality metrics**, for this graph's prompt shape. This is a real
  finding about the existing dashboard, recorded here rather than only in a
  report, so it is not re-litigated the next time someone reads a flat
  Citation Recall line across five modes and assumes the harness is broken.
- **No live per-mode dashboard.** `wiki_metrics.GroundednessRecorder` is a
  single process-wide trailing window with no mode field, retrieval mode is
  fixed per corpus at index time, and an operator's live queries against
  different modes would not be a controlled comparison. The dashboard instead
  gains a mode-attribution label; the actual comparison lives in the committed
  report, consistent with how held-out numbers are handled today.
- **Two docstrings become false and must be corrected in the same change:**
  `wiki_rag.py`'s "deliberate non-goal" paragraph and `wiki_corpus.py`'s
  matching note, plus README §"Retrieval algorithm" and its ADR listing.
- **`EVIDENCE_CARD.md` claims stay per mode.** ADR-0007 already records that
  file overstating a count. A recall or groundedness number from one mode may
  not be quoted for another, and no number may be quoted before the held-out
  run exists.
- **ADR-0006's topology decision is unaffected.** `get_wiki_rag_adapter` keeps
  its `tfidf` default and is deliberately not widened, so the
  planner/single-agent topologies are untouched.

## Alternatives considered

**A. `sentence-transformers` + `all-MiniLM-L6-v2`.** The best-known option and
a smaller model file (~90MB). *Rejected*: it depends on `torch`. On 8GB with a
FastAPI worker and a Next.js dev server already resident, `import torch` alone
costs ~250-400MB RSS before a single weight is loaded — the entire model budget
spent on the framework. `fastembed` covers both the encoder and the
cross-encoder through one `onnxruntime` dependency.

**B. A provider embeddings endpoint (OpenAI/Voyage/Cohere).** Zero local RAM,
better embeddings. *Rejected* for the reason the original docstring already
gives: network and cost on every query, plus it would send the contents of a
private wiki to a third party — a direct contradiction of the corpus-privacy
property `wiki_corpus.py` is designed around. It also makes the eval harness
non-reproducible offline.

**C. pgvector / Qdrant / FAISS as the index.** *Rejected*: at ≤20k chunks an
exact float32 matvec is ~10ms and adds no service. See Decision §4.

**D. A sibling `WikiDenseAdapter` class instead of new modes on the existing
class.** Superficially the cleanest non-regression story. *Rejected*:
`wiki_corpus.py` and `graph/wiki_chat.py` bind to `WikiRagAdapter`'s privates
in several places (`_files`, term counts, `read_evidence`, provenance
back-fill). A sibling class must reproduce all of them, trading one
well-tested class for two partially-tested ones.

**E. Replace `tfidf`/`bm25` with the hybrid mode once it wins.** *Rejected*:
the point of this change is an A/B-testable addition. Nothing is retired
before a held-out number exists, and the lexical modes remain the only
zero-dependency path.

**F. Query expansion / an LLM rewriter instead of dense retrieval.** Cheaper to
build, no model. *Rejected as a substitute*: it adds an LLM call and its
latency/cost to every search, and it cannot recover a document that shares no
vocabulary with any expansion the model happens to produce. Remains available
as a later, orthogonal addition.

**G. Use the shipped `local-fake` provider for the answer-level CI check.**
*Rejected*: `local-fake`'s doc-block regex does not match `wiki_chat`'s prompt
shape and degenerates to identical all-zero metrics for every mode, which
proves nothing about the harness's plumbing. A small scripted-citing fake
double, living in `tests/`, is used instead.

## References

- `src/agentops_workbench/adapters/wiki_rag.py` — the adapter being extended;
  `_VALID_RETRIEVAL_MODES`, `_score`, `MAX_WIKI_DOCS`.
- `src/agentops_workbench/wiki_corpus.py` — registry + provenance path that
  binds to the adapter's internals.
- `src/agentops_workbench/graph/wiki_chat.py` — `read_evidence` consumer;
  numbered (not ref_id) citations; per-turn `thread_id`/history state.
- `src/agentops_workbench/groundedness.py` — the four shipped answer-level
  metrics, all deterministic token-overlap math.
- [ADR-0004](0004-dataset-separation.md) — the 18/6/6 convention instantiated here.
- [ADR-0007](0007-evidence-source-adapter-pattern.md) — §Migration-path step 5
  and §"Honest cost" are the obligations this ADR discharges.
- Robertson & Sparck Jones — Okapi BM25 (existing `bm25` mode).
- Cormack, Clarke & Büttcher (2009) — Reciprocal Rank Fusion, `k=60`.
- Xiao et al. (2023) — BGE / `bge-small-en-v1.5`.
- Nogueira & Cho (2019) — BERT cross-encoder reranking; `ms-marco-MiniLM-L-6-v2`.
- Järvelin & Kekäläinen (2002) — nDCG.
