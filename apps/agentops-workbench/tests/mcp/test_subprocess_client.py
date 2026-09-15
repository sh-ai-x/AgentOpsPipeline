"""Integration test — real MCP stdio subprocess DocumentClient.

Unlike test_document_server.py (in-process `handle_request` calls), this
file spawns the actual document MCP server as a subprocess and talks to it
over real stdio JSON-RPC via `SubprocessDocumentClient`. No mocking of
`subprocess.Popen`.
"""
from __future__ import annotations

import pytest

from agentops_workbench.mcp import DocRef, InMemoryDocumentClient, MCPError
from agentops_workbench.mcp.mcp_servers.document.server import PINNED_PROTOCOL_REVISION
from agentops_workbench.mcp.subprocess_client import SubprocessDocumentClient

# Known fixture doc/substring pair reused from test_document_server.py.
KNOWN_DOC_ID = "doc-001-langgraph-persistence"
KNOWN_SUBSTRING = "PostgresCheckpointer"


@pytest.fixture
def client():
    c = SubprocessDocumentClient()
    try:
        yield c
    finally:
        c.close()


def test_initialize_handshake_validates_pinned_protocol_revision(client) -> None:
    # __init__ already performed the handshake without raising; the client
    # should have recorded what it validated against.
    assert client.protocol_version == PINNED_PROTOCOL_REVISION


def test_search_docs_matches_in_memory_client(client) -> None:
    real_hits = client.search_docs("Postgres", top_k=3)
    in_memory_hits = InMemoryDocumentClient().search_docs("Postgres", top_k=3)

    assert real_hits
    assert real_hits == in_memory_hits
    for hit in real_hits:
        assert isinstance(hit, DocRef)


def test_read_document_returns_real_fixture_text(client) -> None:
    text = client.read_document(KNOWN_DOC_ID)
    assert KNOWN_SUBSTRING in text


def test_read_document_missing_raises_file_not_found(client) -> None:
    with pytest.raises(FileNotFoundError):
        client.read_document("nonexistent-doc-id")


def test_list_filesystem_files_not_implemented(client) -> None:
    with pytest.raises(NotImplementedError):
        client.list_filesystem_files()


def test_context_manager_terminates_subprocess_on_exit() -> None:
    with SubprocessDocumentClient() as c:
        assert c._proc.poll() is None
        proc = c._proc
    assert proc.poll() is not None


def test_dead_process_raises_normalised_error_instead_of_hanging() -> None:
    c = SubprocessDocumentClient()
    try:
        c._proc.kill()
        c._proc.wait(timeout=5)
        with pytest.raises(MCPError):
            c.search_docs("Postgres")
    finally:
        c.close()
