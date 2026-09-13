"""Evidence-source adapters (ADR-0007).

One `EvidenceSourceAdapter` Protocol, N per-deployment implementations,
selected by configuration -- mirrors the `TOPOLOGIES` registry in
`graph/topology.py` and the provider allow-list in `llm/adapter.py`.

None of these adapters are wired into `graph/**` yet; that migration is
explicitly future work (see the PR description for this change).
"""
from __future__ import annotations

from .base import EvidenceRef, EvidenceSourceAdapter, MCPError, classify_mcp_error

__all__ = [
    "EvidenceRef",
    "EvidenceSourceAdapter",
    "MCPError",
    "classify_mcp_error",
]
