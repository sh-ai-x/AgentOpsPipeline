"""Generate the 30-case benchmark (18 dev / 6 val / 6 held_out).

Per proposal §"Phase 3":
  - 18 dev = 3 per family
  -  6 val = 1 per family
  -  6 held_out = 1 per family

Held-out is content-hashed into HELD_OUT_SHA256.txt. Changing any
held-out case requires a new ADR.

This script is idempotent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cases"

FAMILIES = [
    "straightforward", "multi_doc", "ambiguous",
    "missing_evidence", "stale_doc", "tool_failure",
]

# 3 per family (used for dev; first 1 reused for val, second 1 for held_out)
CASE_TEMPLATES = {
    "straightforward": [
        ("How do I configure LangGraph checkpointing with PostgreSQL?",
         "Use a PostgresCheckpointer with a connection string; runs resume after restart.",
         ["search_docs", "read_document"], ["doc://langgraph-persistence"]),
        ("What transport does MCP use for local servers?",
         "stdio (JSON-RPC over stdin/stdout).",
         ["search_docs"], ["doc://mcp-stdio"]),
        ("How do I issue a dev JWT for the workbench API?",
         "issue_token(principal_id) returns a HS256-signed JWT; env JWT_SECRET holds the key.",
         ["search_docs", "read_document"], []),
    ],
    "multi_doc": [
        ("Compare PostgresCheckpointer vs SqliteCheckpointer for a single-node dev workflow.",
         "Postgres for shared/multi-instance; Sqlite for single-node dev. Trade-offs stated.",
         ["search_docs", "read_document"], ["doc://langgraph-persistence", "doc://langgraph-checkpointer-comparison"]),
        ("What is the difference between the LLMAdapter and a raw chat-model call?",
         "The adapter normalises usage (provider, model, tokens, cost_usd) and is the only place that names a provider.",
         ["search_docs", "read_document"], ["doc://llm-adapter"]),
        ("Compare action approval replay vs compensating actions for the mock ticket ledger.",
         "The ledger is idempotent on action_key and rejects mutated args (replay-safe).",
         ["search_docs", "read_document"], []),
    ],
    "ambiguous": [
        ("Why does my graph hang?",
         "Ask for the graph definition + reproducer; do not guess.",
         ["get_issue"], []),
        ("The agent timed out. What now?",
         "Ask which step + the budget; do not guess.",
         ["get_issue"], []),
        ("How do I improve groundedness?",
         "Ask what evidence was retrieved and what the user already tried; do not guess.",
         ["get_issue"], []),
    ],
    "missing_evidence": [
        ("What is the runtime cost of Streamable HTTP transport in MCP?",
         "Insufficient evidence in corpus; supported refusal.",
         ["search_docs"], []),
        ("How many tokens per minute does MiniMax M3 produce?",
         "Insufficient evidence in corpus; supported refusal.",
         ["search_docs"], []),
        ("What is the cold-start latency for the planner/executor variant?",
         "Insufficient evidence in corpus; supported refusal.",
         ["search_docs"], []),
    ],
    "stale_doc": [
        ("How do I use ChatOpenAI with a custom base_url?",
         "Cite the v0.2 docs entry; flag that v0.1 example is stale.",
         ["search_docs", "read_document"], ["doc://langchain-chatopenai-baseurl"]),
        ("Which LangGraph version introduced the typed reducer API?",
         "Cite the version noted in the on-disk docs; flag staleness.",
         ["search_docs", "read_document"], ["doc://langgraph-typed-reducer"]),
        ("Does pyproject.toml use hatchling or setuptools?",
         "Cite the build-backend entry; flag if v0.1 example shows poetry.",
         ["search_docs", "read_document"], []),
    ],
    "tool_failure": [
        ("Search for 'foo bar baz' across the corpus.",
         "search_docs returns empty list; graph surfaces the empty result; no ticket draft.",
         ["search_docs"], []),
        ("Call read_document on a non-existent doc id.",
         "read_document returns an error envelope; graph surfaces it; no ticket draft.",
         ["read_document"], []),
        ("Time out the MCP server mid-call.",
         "MCPError kind=timeout surfaces in the run; no ticket draft.",
         ["search_docs"], []),
    ],
}


def case_id(n: int) -> str:
    return f"case-{n:03d}"


def emit_split(split: str, n_offset: int, out_dir: Path, per_family: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    idx = n_offset
    for family in FAMILIES:
        for k in range(per_family):
            task, outcome, tools, refs = CASE_TEMPLATES[family][k]
            payload = {
                "id": case_id(idx),
                "family_id": family,
                "task": task,
                "expected_outcome": outcome,
                "allowed_tools": tools,
                "source_refs": refs,
                "reviewer": "sh-ai-x",
                "split": split,
            }
            (out_dir / f"{case_id(idx)}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            idx += 1
    return idx


def main() -> None:
    n = 1
    n = emit_split("dev", n, CASES_DIR / "dev", per_family=3)         # 18 cases (001..018)
    n = emit_split("val", n, CASES_DIR / "val", per_family=1)         # 6 cases (019..024)
    n = emit_split("held_out", n, CASES_DIR / "held_out", per_family=1)  # 6 cases (025..030)

    # Back-compat: copy all into fixtures/cases/pilot/ for the existing tests
    pilot_dir = CASES_DIR / "pilot"
    pilot_dir.mkdir(parents=True, exist_ok=True)
    for src_split in ("dev", "val", "held_out"):
        for f in (CASES_DIR / src_split).glob("case-*.json"):
            target = pilot_dir / f.name
            target.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    # Compute held-out SHA256
    held_files = sorted((CASES_DIR / "held_out").glob("case-*.json"))
    h = hashlib.sha256()
    for f in held_files:
        h.update(f.read_bytes())
    (CASES_DIR / "HELD_OUT_SHA256.txt").write_text(h.hexdigest() + "\n", encoding="utf-8")

    print(
        f"wrote {len(list((CASES_DIR / 'dev').glob('*.json')))} dev, "
        f"{len(list((CASES_DIR / 'val').glob('*.json')))} val, "
        f"{len(list((CASES_DIR / 'held_out').glob('*.json')))} held_out"
    )
    print(f"held-out sha256: {h.hexdigest()}")


if __name__ == "__main__":  # pragma: no cover
    main()
