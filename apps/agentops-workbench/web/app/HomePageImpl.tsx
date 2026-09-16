"use client";

import { useCallback, useEffect, useState } from "react";

import MetricsPanel from "./MetricsPanel";

// AC3 trust-field types — must match backend `WikiHit.to_dict()`.
type Hit = {
  ref_id: string;
  title: string;
  score: number;
  source_path: string;
  evidence_span: string;
  match_offsets: [number, number][];
  coverage: number;
  contributing_terms: string[];
  mtime: number;
  // Set only when the indexed directory was an Obsidian vault (browser
  // supplied vault_name on upload). One-click "open in vault" link.
  obsidian_uri?: string | null;
};

type SentenceScore = {
  sentence: string;
  cited_refs: string[];
  unresolved_refs: string[];
  // Three published metrics per sentence (Lin 2004 + Honovich 2022).
  rouge_l_f1: number;
  rouge_l_precision: number;
  rouge_l_recall: number;
  sentence_tokens: number;
  evidence_tokens: number;
  lcs_length: number;
};

type QaResponse = {
  query: string;
  corpus_id: string;
  answer: string;
  // Echoed back so the client can rejoin the conversation on a
  // follow-up turn. Server mints one if `body.thread_id` is None.
  thread_id: string;
  overall_rouge_l_f1: number;
  citation_recall: number;
  citation_precision: number;
  sentences: SentenceScore[];
  hits: Hit[];
};

type IndexResponse = {
  corpus_id: string;
  doc_count: number;
  duration_ms: number;
};

// Mirrors the server's SKIP_DIR_NAMES so client and server agree on
// what to ignore when walking the picked directory.
const SKIP_DIR_NAMES = new Set([
  ".git", ".hg", ".svn", ".obsidian", ".dev-kit", ".claude", ".codex",
  ".serena", ".gemini", ".metagraph", ".trash", ".worktrees", ".venv",
  ".pytest_cache", ".ruff_cache", ".mypy_cache", ".idea", ".vscode",
  "__pycache__", "node_modules", "_flat",
]);

// Recursive walk + junk-skip + .md read. Browser-side mirror of
// `collect_wiki_files` on the server, so what the user sees is what
// gets indexed.
async function walkPickedDir(
  root: FileSystemDirectoryHandle,
): Promise<{ path: string; content: string; mtime: number }[]> {
  const out: { path: string; content: string; mtime: number }[] = [];

  async function visit(
    dir: FileSystemDirectoryHandle,
    prefix: string,
  ): Promise<void> {
    // The directory iterator is async; await each entry.
    // @ts-expect-error -- FileSystemDirectoryHandle.values() types missing in some TS libs
    for await (const entry of dir.values()) {
      if (entry.kind === "directory") {
        if (SKIP_DIR_NAMES.has(entry.name) || entry.name.startsWith(".")) {
          continue;
        }
        const sub = await dir.getDirectoryHandle(entry.name);
        await visit(sub, prefix ? `${prefix}/${entry.name}` : entry.name);
      } else if (entry.kind === "file") {
        if (!entry.name.toLowerCase().endsWith(".md")) continue;
        if (entry.name.startsWith(".")) continue;
        const fh = await dir.getFileHandle(entry.name);
        const file = await fh.getFile();
        const content = await file.text();
        out.push({
          path: prefix ? `${prefix}/${entry.name}` : entry.name,
          content,
          mtime: file.lastModified,
        });
      }
    }
  }

  await visit(root, "");
  return out;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Build a snippet with `<mark>` overlays around the matched term
// positions. The server hands us `evidence_span` + `match_offsets`
// (character positions into the full document); we render the
// substring with `<mark>` tags at those positions.
function highlightSpan(span: string, fullDoc: string, offsets: [number, number][], spanStart: number): React.ReactNode {
  if (!offsets.length) return span;
  // Translate offsets-in-doc to offsets-in-span. We don't know the
  // exact spanStart value the server used, so we approximate by
  // finding each matched term in the span text.
  const tokens = new Set<string>();
  for (const [s, e] of offsets) {
    if (s >= spanStart && e <= spanStart + span.length) {
      tokens.add(fullDoc.slice(s, e));
    }
  }
  if (tokens.size === 0) return span;
  const parts: React.ReactNode[] = [];
  const re = new RegExp(
    Array.from(tokens).map(escapeRegExp).sort((a, b) => b.length - a.length).join("|"),
    "gi",
  );
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = re.exec(span)) !== null) {
    if (match.index > lastIndex) {
      parts.push(span.slice(lastIndex, match.index));
    }
    parts.push(<mark key={key++}>{match[0]}</mark>);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < span.length) {
    parts.push(span.slice(lastIndex));
  }
  return <>{parts}</>;
}

// Color the score: green >= 0.6, amber 0.3-0.6, red < 0.3.
function groundednessColor(score: number): string {
  if (score >= 0.6) return "#16a34a";
  if (score >= 0.3) return "#d97706";
  return "#dc2626";
}

// Reference copy for the two metric families this page shows. Kept as
// data (not scattered prose) so "search" and "qa" can render the same
// entries consistently and so the numbers are never explained differently
// in two places.
const METRIC_DOCS: Record<
  "search" | "qa",
  { label: string; meaning: string; why: string }[]
> = {
  search: [
    {
      label: "score",
      meaning:
        "TF-IDF-weighted cosine similarity between your query and this document, 0–1. Higher = more relevant.",
      why:
        "TF-IDF + cosine is a standard, well-understood retrieval technique — not a bespoke heuristic — so it needs no embedding service and the number means the same thing anyone else measuring TF-IDF similarity would get.",
    },
    {
      label: "coverage",
      meaning:
        "% of the distinct words in your query that were actually found in this document (matched terms ÷ total query terms).",
      why:
        "score can be high from a few heavily-weighted rare terms even if most of your question isn't in the document. coverage is the plain-English check on that: it tells you how much of what you literally typed the document touches.",
    },
    {
      label: "terms",
      meaning:
        "The words in this document that contributed the most to its score — i.e. why it surfaced.",
      why: "Lets you sanity-check a match without opening the source file.",
    },
  ],
  qa: [
    {
      label: "ROUGE-L F1",
      meaning:
        "Overlap between an answer sentence and its cited evidence, via the Longest Common Subsequence (LCS) of tokens (Lin, 2004). Precision = LCS ÷ sentence tokens, Recall = LCS ÷ evidence tokens.",
      why:
        "The standard published metric for summary/answer-vs-source overlap — it rewards matching word order, not just shared vocabulary — used instead of a custom string-similarity function so the score means something outside this app.",
    },
    {
      label: "Citation Recall",
      meaning:
        "Fraction of answer sentences that carry at least one citation resolving to real evidence.",
      why:
        "Answers \"did the LLM even try to attribute its claims?\" (Honovich et al., 2022 — TRUE).",
    },
    {
      label: "Citation Precision",
      meaning:
        "Fraction of the [ref-x] markers the LLM emitted that actually point to real evidence, vs. fabricated.",
      why:
        "Answers \"can you trust the citations it gave you?\" (Honovich et al., 2022 — TRUE). Recall and Precision are independent: an answer can cite everything (100% recall) while citing the wrong thing (low precision).",
    },
  ],
};

function MetricsGuide({ topic }: { topic: "search" | "qa" }) {
  return (
    <details className="metrics-guide">
      <summary>What do these numbers mean?</summary>
      <dl>
        {METRIC_DOCS[topic].map((m) => (
          <div className="metrics-guide-row" key={m.label}>
            <dt>{m.label}</dt>
            <dd>
              {m.meaning}
              <span className="metrics-guide-why">Why this metric: {m.why}</span>
            </dd>
          </div>
        ))}
      </dl>
      {topic === "qa" && (
        <p className="metrics-guide-note">
          All three at 0% usually means the LLM found no supporting evidence
          and explicitly refused to answer rather than guess — that's the
          safe outcome the prompt asks for, not a broken search.
        </p>
      )}
    </details>
  );
}

export default function HomePageImpl() {
  const [bearer, setBearer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<
    | { mode: "manual" }
    | { mode: "dev"; principal: string; expiresIn: number }
  | null
  >(null);
  // Corpus state (after picker).
  const [corpusId, setCorpusId] = useState<string | null>(null);
  const [docCount, setDocCount] = useState<number | null>(null);
  const [indexDurationMs, setIndexDurationMs] = useState<number | null>(null);
  // Search state.
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [hits, setHits] = useState<Hit[] | null>(null);
  // QA state.
  const [qaQuery, setQaQuery] = useState("");
  const [qaResp, setQaResp] = useState<QaResponse | null>(null);
  // Server-minted thread_id for multi-turn chat. Persisted across calls
  // so a follow-up turn resumes the prior conversation by thread_id,
  // not by retransmitting the transcript.
  const [qaThreadId, setQaThreadId] = useState<string | null>(null);

  const authHeaders = useCallback(
    (): Record<string, string> => (bearer ? { Authorization: `Bearer ${bearer}` } : {}),
    [bearer],
  );

  // On mount: probe /v1/auth/dev-mode and, if enabled, auto-mint a
  // token via /v1/auth/dev-token. Production deployments have
  // AGENTOPS_ALLOW_DEV_TOKEN unset -> this is a no-op and the user
  // falls through to the manual Bearer field below.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/v1/auth/dev-mode");
        if (!r.ok) return;
        const info = (await r.json()) as {
          enabled: boolean;
          default_principal: string;
        };
        if (!info.enabled) return;
        const tk = await fetch(
          `/api/v1/auth/dev-token?principal_id=${encodeURIComponent(info.default_principal)}`,
        );
        if (!tk.ok) return;
        const body = (await tk.json()) as {
          token: string;
          principal_id: string;
          expires_in: number;
        };
        if (cancelled) return;
        setBearer(body.token);
        setAuthMode({
          mode: "dev",
          principal: body.principal_id,
          expiresIn: body.expires_in,
        });
      } catch {
        // silent — dev-mode probe failure just means we're in
        // manual auth mode.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // ----- AC1: directory picker -----
  async function onPickDirectory() {
    setError(null);
    if (typeof window === "undefined" || !("showDirectoryPicker" in window)) {
      setError(
        "Your browser does not support the File System Access API. " +
        "Please use a Chromium-based browser (Chrome, Edge, Brave, Arc).",
      );
      return;
    }
    setBusy(true);
    try {
      // The picker triggers the OS permission prompt. On approval
      // we get a handle; on denial it throws an AbortError we
      // surface as a friendly message.
      // @ts-expect-error -- showDirectoryPicker is not in lib.dom typings universally
      const root: FileSystemDirectoryHandle = await window.showDirectoryPicker({ mode: "read" });
      const files = await walkPickedDir(root);
      if (files.length === 0) {
        setError(
          "No .md files found under the picked directory (junk dirs " +
          "skipped). Pick a directory that contains markdown notes.",
        );
        return;
      }
      // POST the files to /v1/wiki/index-files.
      const r = await fetch("/api/v1/wiki/index-files", {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ files }),
      });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const idx = (await r.json()) as IndexResponse;
      setCorpusId(idx.corpus_id);
      setDocCount(idx.doc_count);
      setIndexDurationMs(idx.duration_ms);
      setHits(null);
      setQaResp(null);
      setQaThreadId(null);
    } catch (err) {
      const e = err as Error & { name?: string };
      if (e.name === "AbortError") {
        setError(null);
      } else {
        setError((err as Error).message);
      }
    } finally {
      setBusy(false);
    }
  }

  // ----- AC2 + AC3: search routed to existing WikiRagAdapter with provenance -----
  async function onSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || !bearer || !corpusId) return;
    setBusy(true);
    setError(null);
    setHits(null);
    try {
      const qs = new URLSearchParams({
        corpus_id: corpusId,
        q: query,
        top_k: String(topK),
      });
      const r = await fetch(`/api/v1/wiki/search?${qs.toString()}`, {
        headers: authHeaders(),
      });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const data = (await r.json()) as { results: Hit[] };
      setHits(data.results);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // ----- AC3: QA mode with per-sentence attribution metrics -----
  async function onAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!qaQuery.trim() || !bearer || !corpusId) return;
    setBusy(true);
    setError(null);
    // Multi-turn: keep the server-minted `thread_id` from the prior
    // answer and send it back. The LangGraph checkpointer
    // (`graph/wiki_chat.py`) restores the conversation `history`
    // server-side for that thread_id; we never resend the transcript.
    // Picking a new directory resets the conversation (no thread_id).
    try {
      const r = await fetch("/api/v1/wiki/qa", {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          corpus_id: corpusId,
          query: qaQuery,
          top_k: topK,
          ...(qaThreadId ? { thread_id: qaThreadId } : {}),
        }),
      });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const data = (await r.json()) as QaResponse;
      setQaResp(data);
      setQaThreadId(data.thread_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>AgentOps Wiki</h1>
      <p className="subtitle">
        Pick a local directory of <code>.md</code> notes (Obsidian vault,
        <code>~/dev/mywiki</code>, any layout). Search and ask questions
        grounded in your own knowledge base.
      </p>

      <div className="toolbar">
        {authMode?.mode === "dev" ? (
          <span className="status">
            ✓ dev-mode auto-mint active — signed in as
            <strong> {authMode.principal}</strong>
            (token expires in {Math.round(authMode.expiresIn / 60)} min)
          </span>
        ) : (
          <input
            type="password"
            placeholder="Bearer token (JWT)"
            value={bearer}
            onChange={(e) => setBearer(e.target.value)}
            suppressHydrationWarning
          />
        )}
      </div>

      <section className="card">
        <h2>1. Pick your wiki directory</h2>
        <button onClick={onPickDirectory} disabled={busy || !bearer} className="primary">
          {busy ? "..." : "Pick directory"}
        </button>
        {corpusId && (
          <p className="status">
            ✓ indexed <strong>{docCount}</strong> file
            {docCount === 1 ? "" : "s"} in <strong>{indexDurationMs}ms</strong>
            <br />
            <span className="muted">corpus_id = {corpusId}</span>
          </p>
        )}
      </section>

      {corpusId && (
        <>
          <section className="card">
            <h2>2. Search</h2>
            <MetricsGuide topic="search" />
            <form onSubmit={onSearch} className="search-row">
              <input
                placeholder="search query (e.g. 'langgraph checkpointing')"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <input
                type="number"
                min={1}
                max={20}
                value={topK}
                onChange={(e) =>
                  setTopK(Math.max(1, Math.min(20, Number(e.target.value) || 5)))
                }
                style={{ flex: "0 0 72px" }}
              />
              <button type="submit" className="primary" disabled={busy || !query.trim()}>
                {busy ? "..." : "Search"}
              </button>
            </form>

            {hits !== null && hits.length === 0 && (
              <p className="status">no results</p>
            )}

            {hits?.map((h, i) => (
              <article className="hit" key={`${h.ref_id}-${i}`}>
                <div className="hit-title">
                  {h.obsidian_uri ? (
                    <a
                      className="hit-link"
                      href={h.obsidian_uri}
                      target="_blank"
                      rel="noreferrer"
                      title="Open in Obsidian vault"
                    >
                      <code>{h.source_path}</code> — <em>{h.ref_id}</em>
                    </a>
                  ) : (
                    <>
                      <code>{h.source_path}</code> — <em>{h.ref_id}</em>
                    </>
                  )}
                </div>
                <div className="hit-meta">
                  <span className="metric">
                    score <strong>{h.score.toFixed(3)}</strong>
                  </span>
                  <span className="metric-sep">·</span>
                  <span
                    className="metric"
                    style={{ color: groundednessColor(h.coverage) }}
                  >
                    coverage <strong>{(h.coverage * 100).toFixed(0)}%</strong>
                  </span>
                  <span className="metric-sep">·</span>
                  <span className="metric muted">
                    mtime {new Date(h.mtime).toISOString().slice(0, 19)}
                  </span>
                </div>
                <div className="hit-terms muted">
                  terms: {h.contributing_terms.slice(0, 5).join(", ") || "(none)"}
                </div>
                <pre className="hit-body">
                  {highlightSpan(h.evidence_span, h.evidence_span, h.match_offsets, 0)}
                </pre>
              </article>
            ))}
          </section>

          <section className="card">
            <h2>3. Ask with groundedness</h2>
            <MetricsGuide topic="qa" />
            <form onSubmit={onAsk} className="search-row">
              <input
                placeholder="ask a question (the LLM will cite each claim)"
                value={qaQuery}
                onChange={(e) => setQaQuery(e.target.value)}
              />
              <button type="submit" className="primary" disabled={busy || !qaQuery.trim()}>
                {busy ? "..." : "Ask"}
              </button>
            </form>

            {qaResp && (
              <div className="qa">
                <p className="overall">
                  <strong>ROUGE-L F1</strong>
                  <span
                    className="badge"
                    style={{ backgroundColor: groundednessColor(qaResp.overall_rouge_l_f1) }}
                  >
                    {(qaResp.overall_rouge_l_f1 * 100).toFixed(0)}%
                  </span>
                  <strong style={{ marginLeft: 16 }}>Citation Recall</strong>
                  <span
                    className="badge"
                    style={{ backgroundColor: groundednessColor(qaResp.citation_recall) }}
                  >
                    {(qaResp.citation_recall * 100).toFixed(0)}%
                  </span>
                  <strong style={{ marginLeft: 16 }}>Citation Precision</strong>
                  <span
                    className="badge"
                    style={{ backgroundColor: groundednessColor(qaResp.citation_precision) }}
                  >
                    {(qaResp.citation_precision * 100).toFixed(0)}%
                  </span>
                </p>
                <p className="muted" style={{ marginTop: -8 }}>
                  ROUGE-L F1 (Lin 2004): sentence ↔ cited evidence overlap. Citation Recall + Precision (Honovich 2022): are claims cited, and are the citations real?
                </p>
                <div className="answer">{qaResp.answer}</div>

                <h3>Per-sentence breakdown</h3>
                {qaResp.sentences.map((s, i) => (
                  <div
                    key={i}
                    className="sentence"
                    style={{ borderLeft: `4px solid ${groundednessColor(s.rouge_l_f1)}` }}
                  >
                    <div className="sentence-header">
                      <span
                        className="badge"
                        style={{ backgroundColor: groundednessColor(s.rouge_l_f1) }}
                      >
                        ROUGE-L F1 {(s.rouge_l_f1 * 100).toFixed(0)}%
                      </span>
                      <span className="muted" title="Precision = LCS ÷ sentence tokens. Recall = LCS ÷ evidence tokens.">
                        P={(s.rouge_l_precision * 100).toFixed(0)}% · R={(s.rouge_l_recall * 100).toFixed(0)}%
                      </span>
                      <span className="muted" title="Longest Common Subsequence length, out of the sentence's own token count.">
                        LCS={s.lcs_length}/{s.sentence_tokens} tokens
                      </span>
                      {s.cited_refs.length > 0 && (
                        <span className="muted">
                          cites: {s.cited_refs.map((r) => `[${r}]`).join(" ")}
                        </span>
                      )}
                      {s.unresolved_refs.length > 0 && (
                        <span className="muted" style={{ color: "#dc2626" }}>
                          unresolved: {s.unresolved_refs.map((r) => `[${r}]`).join(" ")}
                        </span>
                      )}
                    </div>
                    <div>{s.sentence}</div>
                  </div>
                ))}

                <h3>Top evidence ({qaResp.hits.length})</h3>
                {qaResp.hits.slice(0, 3).map((h, i) => (
                  <article className="hit" key={`qa-${h.ref_id}-${i}`}>
                    <div className="hit-title">
                      {h.obsidian_uri ? (
                        <a
                          className="hit-link"
                          href={h.obsidian_uri}
                          target="_blank"
                          rel="noreferrer"
                          title="Open in Obsidian vault"
                        >
                          <code>{h.source_path}</code> — <em>{h.ref_id}</em>
                        </a>
                      ) : (
                        <>
                          <code>{h.source_path}</code> — <em>{h.ref_id}</em>
                        </>
                      )}
                    </div>
                    <div className="hit-meta">
                      score <strong>{h.score.toFixed(3)}</strong>
                      {" · "}
                      coverage <strong>{(h.coverage * 100).toFixed(0)}%</strong>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <MetricsPanel />

      {error && (
        <p className="status" style={{ color: "var(--accent)" }}>
          error: {error}
        </p>
      )}
    </main>
  );
}
