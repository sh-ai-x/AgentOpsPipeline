"""Retrieval-mode A/B comparison runner (ADR-0010 §5, step 9).

Builds one `WikiRagAdapter` per retrieval mode over `fixtures/wiki_eval/corpus`,
runs every query in a split, scores each ranking with
`benchmark.retrieval_metrics`, and prints a comparison table -- so "does
dense/hybrid/hybrid_rerank actually beat tfidf/bm25" has a measured answer
instead of an assertion in an ADR.

CLI:
    uv run python -m agentops_workbench.experiments.retrieval_ab \\
        --split dev --k 5 --modes tfidf,bm25,dense,hybrid,hybrid_rerank

`--embedder fake` (the default, and the only offline/CI-safe option) uses a
feature-hashed bag-of-words backend (`_hash_embedding_backend`) -- a real,
deterministic, dependency-free dense signal correlated with token overlap,
NOT a semantic embedding. It is enough to prove the harness's plumbing
(one row per mode, a stable schema, correct artifacts) but not to draw a
retrieval-quality conclusion. `--embedder real` uses the actual
`fastembed`-backed default (ADR-0010 step 10) for a genuine comparison.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..adapters.wiki_rag import _LEXICAL_MODES, _VALID_RETRIEVAL_MODES, WikiRagAdapter
from ..benchmark.retrieval_metrics import (
    collapse_to_parents,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from ..benchmark.wiki_eval_load import WikiEvalQuery, held_out_sha256, load_split
from .held_out import _git_sha

ALL_MODES = sorted(_VALID_RETRIEVAL_MODES)


@dataclass(frozen=True)
class PerQueryResult:
    mode: str
    query_id: str
    family_id: str
    ranked_refs: list[str]
    hit_at_k: float
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    latency_ms: float


@dataclass(frozen=True)
class ModeSummary:
    mode: str
    n_queries: int
    hit_at_k: float
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    index_s: float
    p50_query_ms: float


@dataclass
class ComparisonResult:
    summaries: list[ModeSummary]
    per_query: list[PerQueryResult]


class _HashEmbeddingBackend:
    """Feature-hashed bag-of-words embedding. Deterministic, dependency-free,
    and a REAL (if crude) dense signal: cosine similarity rises with shared
    tokens. Not semantic -- it cannot find a synonym/paraphrase match a real
    embedding model would. Exists so `--embedder fake` exercises the harness
    end-to-end offline; it is not evidence for or against any retrieval
    mode's quality."""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        from ..text_utils import tokenize

        vec = [0.0] * self.dim
        for tok in tokenize(text):
            vec[hash(tok) % self.dim] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def _hash_embedding_backend() -> _HashEmbeddingBackend:
    return _HashEmbeddingBackend()


def _build_adapter(corpus_dir: Path, mode: str, *, embedder: object | None) -> WikiRagAdapter:
    kwargs: dict[str, object] = {}
    # Only non-lexical modes ever look at `embedder` -- WikiRagAdapter itself
    # enforces this (ADR-0010 §1); passing it unconditionally here is safe
    # and is exactly what test_lexical_modes_never_construct_the_injected_embedder
    # pins.
    if mode not in _LEXICAL_MODES and embedder is not None:
        kwargs["embedder"] = embedder
    return WikiRagAdapter(wiki_dir=str(corpus_dir), retrieval=mode, **kwargs)


def _score_query(mode: str, query: WikiEvalQuery, hits: list, k: int, latency_ms: float) -> PerQueryResult:
    ranked_chunk = [h.ref_id for h in hits]
    ranked_file = collapse_to_parents(ranked_chunk)
    gold = query.gold_refs
    grades = query.graded_relevance
    return PerQueryResult(
        mode=mode,
        query_id=query.id,
        family_id=query.family_id,
        ranked_refs=ranked_file[:k],
        hit_at_k=hit_rate_at_k(gold, ranked_file, k),
        recall_at_k=recall_at_k(gold, ranked_file, k),
        precision_at_k=precision_at_k(gold, ranked_file, k),
        mrr=mrr(gold, ranked_file),
        ndcg_at_k=ndcg_at_k(grades, ranked_file, k),
        latency_ms=latency_ms,
    )


def run_mode(
    corpus_dir: Path, mode: str, queries: list[WikiEvalQuery], k: int, *, embedder: object | None
) -> tuple[ModeSummary, list[PerQueryResult]]:
    t0 = time.monotonic()
    adapter = _build_adapter(corpus_dir, mode, embedder=embedder)
    index_s = time.monotonic() - t0

    per_query: list[PerQueryResult] = []
    latencies: list[float] = []
    for query in queries:
        t1 = time.monotonic()
        hits = adapter.search_evidence(query.query, top_k=max(k, 20))
        latency_ms = (time.monotonic() - t1) * 1000.0
        latencies.append(latency_ms)
        per_query.append(_score_query(mode, query, hits, k, latency_ms))

    def _mean(attr: str) -> float:
        return statistics.fmean(getattr(r, attr) for r in per_query) if per_query else 0.0

    summary = ModeSummary(
        mode=mode,
        n_queries=len(per_query),
        hit_at_k=_mean("hit_at_k"),
        recall_at_k=_mean("recall_at_k"),
        precision_at_k=_mean("precision_at_k"),
        mrr=_mean("mrr"),
        ndcg_at_k=_mean("ndcg_at_k"),
        index_s=index_s,
        p50_query_ms=statistics.median(latencies) if latencies else 0.0,
    )
    return summary, per_query


def run_comparison(
    wiki_eval_dir: Path,
    *,
    split: str,
    k: int,
    modes: list[str],
    embedder: object | None,
) -> ComparisonResult:
    corpus_dir = wiki_eval_dir / "corpus"
    queries = load_split(wiki_eval_dir, split)
    summaries: list[ModeSummary] = []
    per_query: list[PerQueryResult] = []
    for mode in modes:
        summary, rows = run_mode(corpus_dir, mode, queries, k, embedder=embedder)
        summaries.append(summary)
        per_query.extend(rows)
    return ComparisonResult(summaries=summaries, per_query=per_query)


def render_report(result: ComparisonResult, *, split: str, k: int) -> str:
    lines: list[str] = []
    lines.append(f"# Retrieval A/B report (split={split}, k={k})\n")
    lines.append(
        f"n={result.summaries[0].n_queries if result.summaries else 0} queries. Metrics are file-level (chunk hits collapsed to their "
        "parent via `collapse_to_parents`) so whole-file and chunk-based modes "
        "are scored on the same unit.\n"
    )

    baseline = next((s for s in result.summaries if s.mode == "bm25"), None)

    header = ["mode", "Hit@k", "R@k", "P@k", "MRR", "nDCG@k", "index_s", "p50_ms"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for s in result.summaries:
        lines.append(
            f"| {s.mode} | {s.hit_at_k:.3f} | {s.recall_at_k:.3f} | {s.precision_at_k:.3f} | {s.mrr:.3f} | {s.ndcg_at_k:.3f} | {s.index_s:.2f} | {s.p50_query_ms:.1f} |"
        )

    if baseline is not None:
        lines.append("\n## Delta vs bm25 (baseline)\n")
        lines.append("| mode | ΔHit@k | ΔR@k | ΔP@k | ΔMRR | ΔnDCG@k |")
        lines.append("|---|---|---|---|---|---|")
        for s in result.summaries:
            if s.mode == "bm25":
                continue
            lines.append(
                f"| {s.mode} | {s.hit_at_k - baseline.hit_at_k:+.3f} | {s.recall_at_k - baseline.recall_at_k:+.3f} | {s.precision_at_k - baseline.precision_at_k:+.3f} | {s.mrr - baseline.mrr:+.3f} | {s.ndcg_at_k - baseline.ndcg_at_k:+.3f} |"
            )

    families = sorted({r.family_id for r in result.per_query})
    modes_seen = [s.mode for s in result.summaries]
    if families:
        lines.append("\n## Per-family nDCG@k\n")
        lines.append("| mode | " + " | ".join(families) + " |")
        lines.append("|" + "|".join(["---"] * (len(families) + 1)) + "|")
        for mode in modes_seen:
            row = [mode]
            for fam in families:
                vals = [r.ndcg_at_k for r in result.per_query if r.mode == mode and r.family_id == fam]
                row.append(f"{statistics.fmean(vals):.3f}" if vals else "—")
            lines.append("| " + " | ".join(row) + " |")

    lines.append(
        "\n_Caveat: this run's `n` is illustrative, not statistically settled. "
        "See docs/adr/0010-dense-retrieval-and-reranking.md for the metrics' "
        "documented limitations (Citation Precision/Recall track prompt "
        "compliance, not retrieval quality, at the answer-level layer)._\n"
    )
    return "\n".join(lines)


def write_artifacts(
    out_dir: Path, result: ComparisonResult, *, split: str, k: int, modes: list[str],
    wiki_eval_dir: Path | None = None, embedder_kind: str = "fake",
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "code_sha": _git_sha(Path.cwd()),
        "split": split,
        "k": k,
        "modes": modes,
        "embedder": embedder_kind,
        "held_out_sha256": held_out_sha256(wiki_eval_dir) if wiki_eval_dir else None,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (out_dir / "per_query.jsonl").open("w", encoding="utf-8") as fh:
        for row in result.per_query:
            fh.write(json.dumps(asdict(row)) + "\n")
    (out_dir / "report.md").write_text(render_report(result, split=split, k=k), encoding="utf-8")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-eval-dir", default="fixtures/wiki_eval")
    parser.add_argument("--split", default="dev", choices=["dev", "val", "held_out"])
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--modes", default=",".join(ALL_MODES))
    parser.add_argument("--embedder", default="fake", choices=["fake", "real"])
    parser.add_argument("--out-dir", default="experiments/retrieval-ab-v1")
    parser.add_argument("--confirm-held-out", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.split == "held_out" and not args.confirm_held_out:
        print(
            "refusing to run against the held_out split without --confirm-held-out "
            "-- tune on dev/val first; held-out is read once (ADR-0004 convention).",
            file=sys.stderr,
        )
        raise SystemExit(2)

    wiki_eval_dir = Path(args.wiki_eval_dir)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    embedder = _hash_embedding_backend() if args.embedder == "fake" else None

    result = run_comparison(wiki_eval_dir, split=args.split, k=args.k, modes=modes, embedder=embedder)
    report = render_report(result, split=args.split, k=args.k)
    print(report)

    write_artifacts(
        Path(args.out_dir), result, split=args.split, k=args.k, modes=modes,
        wiki_eval_dir=wiki_eval_dir, embedder_kind=args.embedder,
    )


if __name__ == "__main__":
    main()
