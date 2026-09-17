"""Load `fixtures/wiki_eval/` gold queries and compute the held-out freeze.

Mirrors `benchmark/load.py`'s `BenchmarkCase` loader shape, but for the
wiki-retrieval gold set (ADR-0010 §5 / ADR-0004's per-source dataset
convention) rather than the answer-level 30-case benchmark -- a separate
instance because, per ADR-0007, "dataset splits are per source... numbers
do not pool across sources."
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WikiEvalQuery:
    id: str
    family_id: str
    query: str
    relevant_refs: tuple[str, ...]
    partially_relevant_refs: tuple[str, ...]
    relevant_sections: tuple[str, ...]
    reviewer: str
    split: str
    expected_answer_contains: tuple[str, ...] = ()

    @property
    def gold_refs(self) -> set[str]:
        """Union of fully- and partially-relevant refs -- what `recall_at_k`
        etc. treat as "found" for the binary metrics."""
        return set(self.relevant_refs) | set(self.partially_relevant_refs)

    @property
    def graded_relevance(self) -> dict[str, int]:
        """ref_id -> grade for `ndcg_at_k`: 2 = fully relevant, 1 = partial."""
        grades = {ref: 1 for ref in self.partially_relevant_refs}
        grades.update({ref: 2 for ref in self.relevant_refs})
        return grades


def load_query(path: Path) -> WikiEvalQuery:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return WikiEvalQuery(
        id=raw["id"],
        family_id=raw["family_id"],
        query=raw["query"],
        relevant_refs=tuple(raw["relevant_refs"]),
        partially_relevant_refs=tuple(raw["partially_relevant_refs"]),
        relevant_sections=tuple(raw["relevant_sections"]),
        reviewer=raw["reviewer"],
        split=raw["split"],
        expected_answer_contains=tuple(raw.get("expected_answer_contains", ())),
    )


def load_split(wiki_eval_dir: Path, split: str) -> list[WikiEvalQuery]:
    """Load every query file under `wiki_eval_dir/queries/<split>/`."""
    split_dir = wiki_eval_dir / "queries" / split
    return [load_query(p) for p in sorted(split_dir.glob("wq-*.json"))]


def held_out_sha256(wiki_eval_dir: Path) -> str:
    """Frozen SHA256 over the held-out query files. Drift breaks the freeze."""
    held_dir = wiki_eval_dir / "queries" / "held_out"
    h = hashlib.sha256()
    for p in sorted(held_dir.glob("wq-*.json")):
        h.update(p.read_bytes())
    return h.hexdigest()
