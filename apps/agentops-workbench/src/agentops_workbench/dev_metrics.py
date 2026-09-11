"""Shared collectors for the workbench's debug metrics.

Lives in a single module so the HTTP endpoint (`/_debug/metrics`) and
the CLI (`scripts/print_metrics.py`) read from the same source. Each
collector is independently cached with a short TTL to keep the HTTP
path cheap under sustained traffic.
"""
from __future__ import annotations

import sqlite3
import subprocess
import time
from pathlib import Path

_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, fn):
    """Return cached value or recompute if stale."""
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _repo_root() -> Path:
    """This file lives at apps/agentops-workbench/src/agentops_workbench/dev_metrics.py.
    Return the workbench root: apps/agentops-workbench/.
    """
    return Path(__file__).resolve().parent.parent.parent


def workbench_root() -> Path:
    """Convenience alias for _repo_root (dev_metrics.py already lives under apps/agentops-workbench)."""
    return _repo_root()


def test_count() -> int:
    def _compute() -> int:
        out = subprocess.run(
            ["uv", "run", "pytest", "--collect-only", "-q"],
            cwd=str(workbench_root()),
            check=False, capture_output=True, text=True, timeout=60,
        ).stdout
        for line in out.splitlines():
            if "tests collected" in line or "test collected" in line:
                return int(line.split()[0].replace("tests", "").replace("test", "").strip())
        return -1
    return _cached("test_count", _compute)


def db_stats() -> dict:
    def _compute() -> dict:
        db = workbench_root() / "agentops.db"
        out = {"runs": 0, "tool_calls": 0, "actions": 0}
        if not db.exists():
            return out
        try:
            conn = sqlite3.connect(str(db))
            cur = conn.cursor()
            for label, table in (("runs", "runs"), ("tool_calls", "tool_calls"), ("actions", "actions")):
                try:
                    cur.execute("SELECT COUNT(*) FROM " + table)
                    out[label] = cur.fetchone()[0]
                except sqlite3.OperationalError:
                    pass
            conn.close()
        except Exception:
            pass
        return out
    return _cached("db_stats", _compute)


def screenshot_stats() -> dict:
    def _compute() -> dict:
        d = workbench_root() / "docs" / "screenshots"
        if not d.exists():
            return {"count": 0, "bytes_total": 0}
        files = list(d.glob("*.png"))
        return {"count": len(files), "bytes_total": sum(p.stat().st_size for p in files)}
    return _cached("screenshot_stats", _compute)


def line_diff_vs_main() -> dict:
    def _compute() -> dict:
        try:
            out = subprocess.run(
                ["git", "diff", "--numstat", "origin/main...HEAD"],
                cwd=str(_repo_root()), check=False, capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except Exception:
            return {"added": 0, "removed": 0}
        a = r = 0
        for line in out.splitlines():
            parts = line.split(chr(9))
            if len(parts) < 3:
                continue
            la, lr = parts[0], parts[1]
            if la == "-" or lr == "-":
                continue
            a += int(la)
            r += int(lr)
        return {"added": a, "removed": r}
    return _cached("line_diff_vs_main", _compute)


def recent_cost_usd() -> float:
    def _compute() -> float:
        db = workbench_root() / "agentops.db"
        if not db.exists():
            return 0.0
        try:
            conn = sqlite3.connect(str(db))
            cur = conn.cursor()
            cur.execute("SELECT cost_usd FROM runs WHERE cost_usd > 0 ORDER BY rowid DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            return float(row[0]) if row else 0.0
        except Exception:
            return 0.0
    return _cached("recent_cost_usd", _compute)
