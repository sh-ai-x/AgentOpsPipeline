"""CLI equivalent of the `/_debug/metrics` HTTP endpoint.

Numbers come from the same shared `agentops_workbench.dev_metrics` module
the endpoint reads, so this CLI and the HTTP surface stay in lockstep --
no duplicated collectors to drift.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the workbench package importable when this file is run directly.
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from agentops_workbench import dev_metrics


def main() -> int:
    print("=" * 72)
    print("AgentOps Workbench - measurable state")
    print("=" * 72)

    print()
    print("## Test suite")
    print(f"  pytest tests collected: {dev_metrics.test_count()}")

    print()
    print("## Local run ledger")
    db = dev_metrics.db_stats()
    print(f"  runs:        {db['runs']}")
    print(f"  tool_calls:  {db['tool_calls']}")
    print(f"  actions:     {db['actions']}")

    print()
    print("## Documentation screenshots")
    sc = dev_metrics.screenshot_stats()
    print(f"  PNG count:   {sc['count']}")
    print(f"  total bytes: {sc['bytes_total']:,}")

    print()
    print("## Current branch vs origin/main (apps/agentops-workbench/ only)")
    diff = dev_metrics.line_diff_vs_main()
    print(f"  +added:      {diff['added']}")
    print(f"  -removed:    {diff['removed']}")

    print()
    print("## Recent cost (last non-zero run)")
    print(f"  cost_usd:    ${dev_metrics.recent_cost_usd():.4f}")

    print()
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
