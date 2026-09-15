"""MCP tool layer.

Wraps the document MCP server (stdio) and the pinned
@modelcontextprotocol/server-filesystem. Tools:
  - search_docs(query, top_k) -> list[doc_id]
  - read_document(doc_id, offset, limit) -> text
  - list_filesystem_files() -> list[str]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocRef:
    doc_id: str
    title: str
    score: float


class DocumentClient(Protocol):
    """Minimal MCP client surface used by the agent graph."""

    def search_docs(self, query: str, top_k: int = 5) -> list[DocRef]: ...
    def read_document(self, doc_id: str, offset: int = 0, limit: int = 2000) -> str: ...
    def list_filesystem_files(self) -> list[str]: ...


class InMemoryDocumentClient:
    """Stand-in for the real MCP client. Reads fixtures/docs/ directly so the
    graph can run in tests without an MCP subprocess.

    The real subprocess-based client is wired in step 6 (worker).
    """

    def __init__(self, docs_dir: str | None = None) -> None:
        if docs_dir is None:
            docs_dir = str(
                Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "docs"
            )
        self._docs_dir = docs_dir
        self._files: list[Path] = sorted(Path(docs_dir).glob("*.md"))

    def search_docs(self, query: str, top_k: int = 5) -> list[DocRef]:
        tokens = [t.lower() for t in query.split() if t]
        scored: list[DocRef] = []
        for f in self._files:
            text = f.read_text(encoding="utf-8", errors="replace").lower()
            hits = sum(text.count(t) for t in tokens)
            if hits == 0:
                continue
            scored.append(DocRef(doc_id=f.stem, title=f.stem.replace("-", " "), score=float(hits)))
        scored.sort(key=lambda r: -r.score)
        return scored[:top_k]

    def read_document(self, doc_id: str, offset: int = 0, limit: int = 2000) -> str:
        path = Path(self._docs_dir) / f"{doc_id}.md"
        if not path.exists():
            raise FileNotFoundError(f"doc not found: {doc_id}")
        text = path.read_text(encoding="utf-8")
        return text[offset : offset + limit]

    def list_filesystem_files(self) -> list[str]:
        return [f.name for f in self._files]


def build_document_client(
    corpus_dir: str,
    wiki_mode: bool,
    document_client: DocumentClient | None = None,
) -> DocumentClient | None:
    """Adapter-selection factory shared by `run_planner_executor` and `run_single_agent`.

    Returns the explicit `document_client` when one is injected
    (test/CI overrides). Otherwise:

    - `wiki_mode=True`  → `WikiRagAdapter(corpus_dir)` (TF-IDF over *.md)
    - `wiki_mode=False` → `InMemoryDocumentClient()` (substring scan)

    The wiki_mode discriminator prevents an operator who only overrode
    `AGENTOPS_DOCS_DIR` from silently switching the planner/single_agent
    topologies to a different retrieval algorithm — the operator has to
    explicitly set `AGENTOPS_WIKI_DIR` (or pass `wiki_mode=True` from
    server.py via `Settings.resolved_corpus`) to opt into TF-IDF.
    """
    if document_client is not None:
        return document_client
    if wiki_mode:
        from ..adapters.wiki_rag import WikiRagAdapter

        return WikiRagAdapter(corpus_dir)
    return InMemoryDocumentClient()


class MCPError(Exception):
    """Normalised MCP error envelope."""

    def __init__(self, kind: str, message: str, source: str = "mcp") -> None:
        super().__init__(f"[{kind}] {source}: {message}")
        self.kind = kind
        self.message = message
        self.source = source


def classify_mcp_error(exc: Exception) -> MCPError:
    """Wrap a raw exception into MCPError. Covers timeout / disconnect /
    malformed / unsupported_capability / permission_denied.
    """
    msg = str(exc)
    name = exc.__class__.__name__.lower()
    if "timeout" in name or "timeout" in msg.lower():
        return MCPError("timeout", msg)
    if "disconnect" in name or "disconnect" in msg.lower() or "broken pipe" in msg.lower() or "brokenpipe" in name:
        return MCPError("disconnect", msg)
    if (
        "schema" in name
        or "validation" in name
        or "decode" in name
        or "schema" in msg.lower()
        or "validation" in msg.lower()
        or "decode" in msg.lower()
    ):
        return MCPError("malformed", msg)
    if "unsupported" in msg.lower() or "not supported" in msg.lower():
        return MCPError("unsupported_capability", msg)
    if "permission" in msg.lower() or "denied" in msg.lower():
        return MCPError("permission_denied", msg)
    return MCPError("unknown", msg)


def is_within_scope(path: str, allowed_root: str) -> bool:
    """Refuse paths outside allowed_root. Used to enforce fixture-only scope."""
    from os.path import abspath, commonpath, realpath

    p = realpath(abspath(path))
    r = realpath(abspath(allowed_root))
    try:
        commonpath([p, r])
        return p == r or p.startswith(r + "/")
    except ValueError:
        return False
