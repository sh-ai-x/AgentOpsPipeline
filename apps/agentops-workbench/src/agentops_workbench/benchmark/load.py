"""Load benchmark cases from disk and compute held-out SHA256 for the freeze."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .scorers import BenchmarkCase


def load_case(path: Path) -> BenchmarkCase:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return BenchmarkCase(
        id=raw["id"],
        family_id=raw["family_id"],
        task=raw["task"],
        expected_outcome=raw["expected_outcome"],
        allowed_tools=tuple(raw["allowed_tools"]),
        source_refs=tuple(raw["source_refs"]),
        reviewer=raw["reviewer"],
        split=raw["split"],
    )


def load_split(cases_dir: Path, split: str) -> list[BenchmarkCase]:
    """Load all cases whose split field == split."""
    out = []
    for p in sorted(cases_dir.glob("case-*.json")):
        c = load_case(p)
        if c.split == split:
            out.append(c)
    return out


def held_out_sha256(cases_dir: Path) -> str:
    """Frozen SHA256 over the held-out cases. Drift breaks the freeze."""
    held_dir = cases_dir / "held_out"
    held = sorted(held_dir.glob("case-*.json"))
    h = hashlib.sha256()
    for p in held:
        h.update(p.read_bytes())
    return h.hexdigest()
