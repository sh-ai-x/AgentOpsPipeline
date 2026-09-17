"""CLI wrapper for the retrieval A/B comparison runner (ADR-0010 step 9).

    uv run python scripts/eval_retrieval.py --split dev --k 5 \\
        --modes tfidf,bm25,dense,hybrid,hybrid_rerank --embedder real

Prints the comparison report and writes
`experiments/retrieval-ab-v1/{manifest.json,per_query.jsonl,report.md}`.
`--embedder real` requires the `[dense]` extra installed
(`uv sync --extra dense`); `--embedder fake` (the default) runs fully
offline via a feature-hashed bag-of-words backend -- see
`agentops_workbench.experiments.retrieval_ab` module docstring for why
that is a plumbing check, not a quality measurement.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the workbench package importable when this file is run directly.
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from agentops_workbench.experiments.retrieval_ab import main

if __name__ == "__main__":
    main()
