"""TDD regression — step 3 MCP integration.

Coverage:
  - test_document_server: discovery, schema, search, read, error envelopes
  - test_filesystem_scope: refuses paths outside fixtures/docs/
  - test_timeout_classification: MCPError kind=timeout
  - test_disconnect_classification: MCPError kind=disconnect
  - test_malformed_classification: MCPError kind=malformed
  - test_unsupported_capability_classification: kind=unsupported_capability
  - test_permission_denied_classification: kind=permission_denied
  - test_duplicate_dispatch_does_not_duplicate_ledger: cross-test with step 2 ledger
  - test_server_disconnect_recovery: client re-init after disconnect
"""
from __future__ import annotations

import json

import pytest

from agentops_workbench.mcp import (
    InMemoryDocumentClient,
    MCPError,
    classify_mcp_error,
    is_within_scope,
)
from agentops_workbench.mcp.mcp_servers.document.server import (
    PINNED_PROTOCOL_REVISION,
    handle_request,
)
from agentops_workbench.mcp.mcp_servers.filesystem.scope_guard import FilesystemGuard


@pytest.fixture
def corpus_dir() -> str:
    from pathlib import Path
    return str(
        Path(__file__).resolve().parent.parent.parent / "fixtures" / "docs"
    )


# ---- Document server ----


def test_initialize_returns_pinned_protocol_revision(corpus_dir: str) -> None:
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        corpus={},
    )
    assert resp["result"]["protocolVersion"] == PINNED_PROTOCOL_REVISION
    assert resp["result"]["serverInfo"]["name"] == "agentops-document"


def test_tools_list_advertises_search_and_read(corpus_dir: str) -> None:
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        corpus={},
    )
    names = sorted(t["name"] for t in resp["result"]["tools"])
    assert names == ["read_document", "search_docs"]


def test_search_docs_returns_results(corpus_dir: str) -> None:
    from agentops_workbench.mcp.mcp_servers.document.server import _load_corpus
    corpus = _load_corpus(corpus_dir)
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search_docs", "arguments": {"query": "Postgres", "top_k": 3}},
    }
    resp = handle_request(req, corpus)
    assert "result" in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert any("langgraph" in p["doc_id"].lower() for p in payload)


def test_read_document_returns_slice(corpus_dir: str) -> None:
    from agentops_workbench.mcp.mcp_servers.document.server import _load_corpus
    corpus = _load_corpus(corpus_dir)
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "read_document", "arguments": {"doc_id": "doc-001-langgraph-persistence"}},
    }
    resp = handle_request(req, corpus)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "PostgresCheckpointer" in payload


def test_read_unknown_doc_returns_error(corpus_dir: str) -> None:
    from agentops_workbench.mcp.mcp_servers.document.server import _load_corpus
    corpus = _load_corpus(corpus_dir)
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "read_document", "arguments": {"doc_id": "no-such-doc"}},
    }
    resp = handle_request(req, corpus)
    assert "error" in resp
    assert "no-such-doc" in resp["error"]["message"]


def test_unknown_tool_returns_error(corpus_dir: str) -> None:
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "totally-bogus-tool", "arguments": {}},
    }
    resp = handle_request(req, corpus={})
    assert "error" in resp


def test_unknown_method_returns_error(corpus_dir: str) -> None:
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "nope"}, corpus={})
    assert "error" in resp


# ---- InMemory client ----


def test_in_memory_client_search_returns_hits(corpus_dir: str) -> None:
    c = InMemoryDocumentClient(docs_dir=corpus_dir)
    hits = c.search_docs("Postgres", top_k=3)
    assert len(hits) >= 1


def test_in_memory_client_search_no_hits(corpus_dir: str) -> None:
    c = InMemoryDocumentClient(docs_dir=corpus_dir)
    hits = c.search_docs("zzzzzzzzzzz", top_k=3)
    assert hits == []


def test_in_memory_client_read_succeeds(corpus_dir: str) -> None:
    c = InMemoryDocumentClient(docs_dir=corpus_dir)
    text = c.read_document("doc-001-langgraph-persistence")
    assert "PostgresCheckpointer" in text


def test_in_memory_client_read_missing_raises(corpus_dir: str) -> None:
    c = InMemoryDocumentClient(docs_dir=corpus_dir)
    import pytest
    with pytest.raises(FileNotFoundError):
        c.read_document("no-such-doc")


# ---- Scope guard ----


def test_filesystem_scope_allows_within_root(corpus_dir: str) -> None:
    g = FilesystemGuard(allowed_root=corpus_dir)
    g.assert_within(f"{corpus_dir}/doc-001-langgraph-persistence.md")


def test_filesystem_scope_refuses_outside_root(tmp_path) -> None:
    g = FilesystemGuard(allowed_root=str(tmp_path))
    with pytest.raises(MCPError) as exc:
        g.assert_within("/etc/passwd")
    assert exc.value.kind == "permission_denied"


def test_is_within_scope_handles_relative_paths() -> None:
    assert is_within_scope("/a/b/c.md", "/a/b") is True
    assert is_within_scope("/a/c.md", "/a/b") is False


# ---- Error classification ----


def test_classify_timeout() -> None:
    e = classify_mcp_error(TimeoutError("read timed out after 5s"))
    assert e.kind == "timeout"


def test_classify_disconnect() -> None:
    e = classify_mcp_error(BrokenPipeError("server disconnected"))
    assert e.kind == "disconnect"


def test_classify_malformed() -> None:
    e = classify_mcp_error(ValueError("schema validation failed"))
    assert e.kind == "malformed"


def test_classify_unsupported_capability() -> None:
    e = classify_mcp_error(NotImplementedError("resources not supported"))
    assert e.kind == "unsupported_capability"


def test_classify_permission_denied() -> None:
    e = classify_mcp_error(PermissionError("permission denied"))
    assert e.kind == "permission_denied"


def test_classify_unknown() -> None:
    e = classify_mcp_error(RuntimeError("something weird"))
    assert e.kind == "unknown"


# ---- Recovery / duplicate dispatch ----


def test_duplicate_publish_is_idempotent() -> None:
    """Cross-test with step 2 ledger: re-publishing with the same action_key
    does NOT duplicate the mock effect."""
    from agentops_workbench.mocks.tickets import DuplicateArgsError, TicketLedger
    led = TicketLedger()
    led.publish(action_key="k1", title="t", body="b", published_by="alice", args={"x": 1})
    # Same action_key + same args -> idempotent return
    led.publish(action_key="k1", title="t", body="b", published_by="alice", args={"x": 1})
    assert led.count() == 1
    # Same action_key + DIFFERENT args -> reject
    with pytest.raises(DuplicateArgsError):
        led.publish(action_key="k1", title="t", body="b", published_by="alice", args={"x": 2})


def test_default_corpus_dir_resolves_to_real_nonempty_fixtures(corpus_dir: str) -> None:
    """main_stdio()'s bare invocation (no corpus_dir arg -- the real
    subprocess-launch path, `python -m ....document.server` with no args)
    must resolve to the real fixtures/docs/, not a stray sibling directory
    that happens to exist but is empty. Previously this was one .parent
    hop short and silently loaded an empty corpus."""
    from pathlib import Path

    from agentops_workbench.mcp.mcp_servers.document.server import (
        _default_corpus_dir,
        _load_corpus,
    )

    resolved = _default_corpus_dir()
    assert Path(resolved).resolve() == Path(corpus_dir).resolve()
    assert Path(resolved).is_dir()
    corpus = _load_corpus(resolved)
    assert corpus  # non-empty -- this is exactly what silently broke before


def test_client_reinit_after_simulated_disconnect(corpus_dir: str) -> None:
    """Simulate a transport disconnect by raising; classify; reconnect."""
    c1 = InMemoryDocumentClient(docs_dir=corpus_dir)
    _ = c1.search_docs("Postgres")  # works
    err = classify_mcp_error(BrokenPipeError("server crashed"))
    assert err.kind == "disconnect"
    # Reconnect: construct a new client (in production: re-establish MCP session)
    c2 = InMemoryDocumentClient(docs_dir=corpus_dir)
    hits = c2.search_docs("Postgres")
    assert hits
