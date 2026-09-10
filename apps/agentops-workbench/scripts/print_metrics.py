"""Print measurable state for the workbench app.

Numbers are pulled live from git, the local DB, the PR (if any), and the
screenshot directory so the values stay in sync with the actual code. The
README's "Metrics" section is a snapshot -- re-run this script after
material changes to refresh.

Usage:
    uv run python scripts/print_metrics.py
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKBENCH = REPO_ROOT / "apps" / "agentops-workbench"
DB_PATH = WORKBENCH / "agentops.db"
SCREENSHOT_DIR = WORKBENCH / "docs" / "screenshots"


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_count() -> int:
    """Total pytest tests, summed across the suite (parsed from collection)."""
    out = subprocess.run(
        ["uv", "run", "pytest", "--collect-only", "-q"],
        cwd=WORKBENCH,
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    # pytest prints "<N> tests collected" near the end
    for line in out.splitlines():
        if "tests collected" in line or "test collected" in line:
            return int(line.split()[0].replace("tests", "").replace("test", "").strip())
    return -1


def screenshot_count() -> tuple[int, int]:
    """Returns (count, total_bytes) for PNGs under docs/screenshots/."""
    pngs = list(SCREENSHOT_DIR.glob("*.png")) if SCREENSHOT_DIR.exists() else []
    return len(pngs), sum(p.stat().st_size for p in pngs)


def db_stats() -> dict:
    """Read counts from the SQLite run ledger."""
    if not DB_PATH.exists():
        return {"runs": 0, "tool_calls": 0, "actions": 0}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    out: dict = {}
    for label, table in [("runs", "runs"), ("tool_calls", "tool_calls"), ("actions", "actions")]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            out[label] = cur.fetchone()[0]
        except sqlite3.OperationalError:
            out[label] = 0
    conn.close()
    return out


def pr_metrics(pr_number: int) -> dict:
    """Return PR head SHA, check counts, review verdict."""
    out = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--json", "headRefOid,mergeable,reviewDecision"],
        check=False, capture_output=True, text=True,
    ).stdout
    if not out:
        return {}
    pr = json.loads(out)
    checks = subprocess.run(
        ["gh", "pr", "checks", str(pr_number), "--json", "name,conclusion"],
        check=False, capture_output=True, text=True,
    ).stdout
    check_data = json.loads(checks) if checks else []
    by_conclusion: dict[str, int] = {}
    for c in check_data:
        by_conclusion[c.get("conclusion") or "pending"] = by_conclusion.get(c.get("conclusion") or "pending", 0) + 1
    return {
        "head_sha": (pr.get("headRefOid") or "")[:7],
        "mergeable": pr.get("mergeable"),
        "review_decision": pr.get("reviewDecision") or "(none)",
        "checks": by_conclusion,
    }


def line_diff_vs_main() -> tuple[int, int]:
    """(+added, -removed) line counts in apps/agentops-workbench/ vs origin/main."""
    try:
        out = subprocess.run(
            ["git", "diff", "--numstat", "origin/main...HEAD", "--", "apps/agentops-workbench/"],
            cwd=REPO_ROOT, check=False, capture_output=True, text=True,
        ).stdout.strip()
    except Exception:
        return 0, 0
    add = rem = 0
    for line in out.splitlines():
        a, r, _ = line.split("\t", 2)
        if a == "-": continue  # binary
        add += int(a); rem += int(r)
    return add, rem


def main() -> int:
    print("=" * 72)
    print("AgentOps Workbench — measurable state")
    print("=" * 72)

    print()
    print("## Test suite")
    n = test_count()
    print(f"  pytest tests collected: {n}")

    print()
    print("## Local run ledger (apps/agentops-workbench/agentops.db)")
    db = db_stats()
    print(f"  runs:        {db['runs']}")
    print(f"  tool_calls:  {db['tool_calls']}")
    print(f"  actions:     {db['actions']}")

    print()
    print("## Documentation screenshots (apps/agentops-workbench/docs/screenshots/)")
    sc, sb = screenshot_count()
    print(f"  PNG count:   {sc}")
    print(f"  total bytes: {sb:,}")

    print()
    print("## Current branch vs origin/main (apps/agentops-workbench/ only)")
    a, r = line_diff_vs_main()
    print(f"  +added:      {a}")
    print(f"  -removed:    {r}")

    pr_num = int(git("rev-parse", "--abbrev-ref", "HEAD").removeprefix("chore/").removeprefix("feat/").removeprefix("fix/").strip() or "0") or 0
    # We can't reliably derive PR number from branch; try the API:
    out = subprocess.run(
        ["gh", "pr", "view", "--json", "number"],
        check=False, capture_output=True, text=True,
    ).stdout
    pr_num = 0
    if out:
        try:
            pr_num = int(json.loads(out).get("number", 0))
        except (json.JSONDecodeError, ValueError):
            pr_num = 0

    if pr_num:
        print()
        print(f"## PR #{pr_num}")
        m = pr_metrics(pr_num)
        for k, v in m.items():
            if k == "checks":
                print(f"  checks: {v}")
            else:
                print(f"  {k}: {v}")

    print()
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
