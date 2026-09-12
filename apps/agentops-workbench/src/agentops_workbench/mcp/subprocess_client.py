"""Real MCP stdio subprocess client for the document server.

`InMemoryDocumentClient` (in `agentops_workbench.mcp`) reads
`fixtures/docs/*.md` directly, in-process, with no JSON-RPC involved.
`SubprocessDocumentClient` is a drop-in alternative that satisfies the same
`DocumentClient` protocol shape but actually launches
`agentops_workbench.mcp.mcp_servers.document.server` as a real subprocess
and talks to it over the real stdio JSON-RPC protocol implemented by that
module's `main_stdio()` / `handle_request()`.

Not wired in as a default anywhere (graph/**, api/server.py) — see the PR
description for why.
"""
from __future__ import annotations

import json
import select
import subprocess
import sys
from pathlib import Path

from agentops_workbench.mcp import DocRef, MCPError, classify_mcp_error
from agentops_workbench.mcp.mcp_servers.document.server import PINNED_PROTOCOL_REVISION

_SERVER_MODULE = "agentops_workbench.mcp.mcp_servers.document.server"

# Read timeout for a single request/response round trip, in seconds.
# Generous because CI machines can be slow to schedule the subprocess.
_READ_TIMEOUT_S = 10.0


def _default_corpus_dir() -> str:
    """The real `fixtures/docs/` corpus, relative to this file.

    `main_stdio()`'s own default (`server.py`, when no `corpus_dir` is
    passed) walks `Path(__file__).resolve().parent` up 5 levels, landing on
    `src/` instead of the package root one level above it — one `.parent`
    short of `fixtures/docs/`, so a bare `python -m ...server` run falls
    back to an empty corpus. That bug lives in a file this client is
    scoped not to touch, so `SubprocessDocumentClient` always launches with
    an explicit `corpus_dir` (a parameter `main_stdio()` already accepts)
    computed independently here instead of depending on that default.
    """
    return str(Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "docs")


class SubprocessDocumentClient:
    """DocumentClient implementation backed by a real stdio MCP subprocess.

    Launches the document MCP server as a child process, performs the
    `initialize` handshake, and speaks newline-delimited JSON-RPC over its
    stdin/stdout pipes for every subsequent call.
    """

    def __init__(self) -> None:
        self._next_id = 1
        self.protocol_version: str | None = None
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import importlib, sys; "
                    f"m = importlib.import_module({_SERVER_MODULE!r}); "
                    "m.main_stdio(sys.argv[1])"
                ),
                _default_corpus_dir(),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
        try:
            self._handshake()
        except Exception:
            self.close()
            raise

    def _handshake(self) -> None:
        try:
            resp = self._call("initialize", {})
        except MCPError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise classify_mcp_error(exc) from exc

        if "error" in resp:
            err = resp["error"]
            raise MCPError("malformed", f"initialize failed: {err.get('message')}")

        protocol_version = resp.get("result", {}).get("protocolVersion")
        if protocol_version != PINNED_PROTOCOL_REVISION:
            raise MCPError(
                "malformed",
                f"protocol mismatch: expected {PINNED_PROTOCOL_REVISION!r}, "
                f"got {protocol_version!r}",
            )
        self.protocol_version = protocol_version

    def _call(self, method: str, params: dict) -> dict:
        if self._proc.poll() is not None or self._proc.stdin is None or self._proc.stdout is None:
            raise MCPError("disconnect", "subprocess is not running")

        req_id = self._next_id
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        try:
            self._proc.stdin.write(json.dumps(request) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise classify_mcp_error(exc) from exc

        try:
            ready, _, _ = select.select([self._proc.stdout], [], [], _READ_TIMEOUT_S)
        except (OSError, ValueError) as exc:
            raise classify_mcp_error(exc) from exc
        if not ready:
            raise MCPError(
                "timeout", f"no response from subprocess within {_READ_TIMEOUT_S}s"
            )

        try:
            line = self._proc.stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            raise classify_mcp_error(exc) from exc

        if not line:
            raise MCPError("disconnect", "subprocess closed its stdout (empty read)")

        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise classify_mcp_error(exc) from exc

    def search_docs(self, query: str, top_k: int = 5) -> list[DocRef]:
        resp = self._call(
            "tools/call",
            {"name": "search_docs", "arguments": {"query": query, "top_k": top_k}},
        )
        if "error" in resp:
            err = resp["error"]
            raise MCPError("unknown", str(err.get("message")))
        text = resp["result"]["content"][0]["text"]
        payload = json.loads(text)
        return [DocRef(doc_id=d["doc_id"], title=d["title"], score=d["score"]) for d in payload]

    def read_document(self, doc_id: str, offset: int = 0, limit: int = 2000) -> str:
        resp = self._call(
            "tools/call",
            {
                "name": "read_document",
                "arguments": {"doc_id": doc_id, "offset": offset, "limit": limit},
            },
        )
        if "error" in resp:
            err = resp["error"]
            if err.get("code") == -32602:
                raise FileNotFoundError(f"doc not found: {doc_id}")
            raise MCPError("unknown", str(err.get("message")))
        text = resp["result"]["content"][0]["text"]
        return json.loads(text)

    def list_filesystem_files(self) -> list[str]:
        raise NotImplementedError(
            "the document MCP server has no filesystem-listing tool; "
            "that belongs to the separate @modelcontextprotocol/server-filesystem"
        )

    def close(self) -> None:
        proc = getattr(self, "_proc", None)
        if proc is None:
            return
        try:
            if proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            except OSError:
                pass
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except OSError:
                pass

    def __enter__(self) -> SubprocessDocumentClient:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
