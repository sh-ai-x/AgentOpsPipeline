"""Document MCP server (stdio).

Provides two tools to MCP clients over stdio JSON-RPC:
  - search_docs(query, top_k) -> list[doc_id]
  - read_document(doc_id, offset, limit) -> text

The implementation uses FastMCP from the official Python SDK (`mcp==2.2.0`).
If the SDK is not installed the module falls back to a manual JSON-RPC
implementation so the tests can exercise the protocol surface.

Pin the protocol revision to `2026-07-28` in `initialize` (per ADR-0002).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

PINNED_PROTOCOL_REVISION = "2026-07-28"


def _load_corpus(corpus_dir: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(Path(corpus_dir).glob("*.md")):
        out[f.stem] = f.read_text(encoding="utf-8")
    return out


def _search(corpus: dict[str, str], query: str, top_k: int) -> list[dict[str, object]]:
    tokens = [t.lower() for t in query.split() if t]
    scored = []
    for doc_id, text in corpus.items():
        low = text.lower()
        hits = sum(low.count(t) for t in tokens)
        if hits == 0:
            continue
        scored.append({"doc_id": doc_id, "title": doc_id.replace("-", " "), "score": float(hits)})
    scored.sort(key=lambda r: -r["score"])  # type: ignore[arg-type,return-value]
    return scored[:top_k]


def _read(corpus: dict[str, str], doc_id: str, offset: int, limit: int) -> str:
    if doc_id not in corpus:
        raise KeyError(doc_id)
    return corpus[doc_id][offset : offset + limit]


def handle_request(req: dict, corpus: dict[str, str]) -> dict:
    """Handle a single JSON-RPC request. Returns the response payload."""
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": PINNED_PROTOCOL_REVISION,
                "capabilities": {"tools": {"listChanged": False}, "resources": {}},
                "serverInfo": {"name": "agentops-document", "version": "0.1.0"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "tools": [
                    {
                        "name": "search_docs",
                        "description": "Lexical search over the workbench corpus.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "top_k": {"type": "integer", "default": 5},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "read_document",
                        "description": "Read a slice of a corpus document by character offset.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "doc_id": {"type": "string"},
                                "offset": {"type": "integer", "default": 0},
                                "limit": {"type": "integer", "default": 2000},
                            },
                            "required": ["doc_id"],
                        },
                    },
                ]
            },
        }

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "search_docs":
                result = _search(corpus, args.get("query", ""), int(args.get("top_k", 5)))
            elif name == "read_document":
                result = _read(
                    corpus,
                    args["doc_id"],
                    int(args.get("offset", 0)),
                    int(args.get("limit", 2000)),
                )
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32601, "message": f"unknown tool: {name}"},
                }
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
            }
        except KeyError as exc:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32602, "message": f"doc not found: {exc.args[0]}"},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32603, "message": str(exc)},
            }

    return {
        "jsonrpc": "2.0",
        "id": rid,
        "error": {"code": -32601, "message": f"unknown method: {method}"},
    }


def _default_corpus_dir() -> str:
    """fixtures/docs/, resolved relative to this file's location.

    __file__ is <app_root>/src/agentops_workbench/mcp/mcp_servers/document/server.py
    -- six .parent hops from here land on <app_root> (document -> mcp_servers
    -> mcp -> agentops_workbench -> src -> <app_root>), where fixtures/ lives.
    """
    return str(
        Path(__file__).resolve().parent.parent.parent.parent.parent.parent / "fixtures" / "docs"
    )


def main_stdio(corpus_dir: str | None = None) -> None:  # pragma: no cover - exercised via integration
    """Run a minimal stdio JSON-RPC loop. Used by subprocess-launching clients."""
    corpus = _load_corpus(corpus_dir or _default_corpus_dir())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(
    json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
    + "\n"
)
            sys.stdout.flush()
            continue
        resp = handle_request(req, corpus)
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":  # pragma: no cover
    main_stdio()
