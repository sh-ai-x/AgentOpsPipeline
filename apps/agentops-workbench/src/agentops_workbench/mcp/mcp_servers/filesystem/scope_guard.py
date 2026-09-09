"""Pinned @modelcontextprotocol/server-filesystem scope guard.

In step 6 this module is replaced by a thin subprocess launcher for
@modelcontextprotocol/server-filesystem@<pinned-version>. The guard
function below is the assertion that holds regardless of transport:

  - The exposed root is exactly `fixtures/docs/` (or any user-provided
    allowed_root passed by the worker).
  - Any path outside that root returns `permission_denied` (MCPError
    kind=permission_denied) and is logged.

The integration test in tests/mcp/test_filesystem_scope.py asserts the
negative case: attempting to read `/etc/passwd` returns permission_denied.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ... import MCPError, is_within_scope

log = logging.getLogger(__name__)

PINNED_FILESYSTEM_VERSION = "2025.6.7"  # from .env.example; see ADR-0002


@dataclass(frozen=True)
class FilesystemGuard:
    allowed_root: str

    def assert_within(self, path: str) -> None:
        if not is_within_scope(path, self.allowed_root):
            log.warning("filesystem access refused: path=%s root=%s", path, self.allowed_root)
            raise MCPError(
                kind="permission_denied",
                message=f"path outside allowed root: {path}",
                source="filesystem_pin",
            )
