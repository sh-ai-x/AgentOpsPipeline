"""EvidenceRef / EvidenceSourceAdapter Protocol shape + re-exports."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agentops_workbench.adapters.base import (
    EvidenceRef,
    EvidenceSourceAdapter,
    MCPError,
    classify_mcp_error,
)
from agentops_workbench.mcp import MCPError as MCPErrorFromMCP
from agentops_workbench.mcp import classify_mcp_error as classify_mcp_error_from_mcp


def test_evidence_ref_is_frozen_and_carries_required_fields() -> None:
    ref = EvidenceRef(
        ref_id="wiki:notes/foo",
        title="foo",
        score=3.5,
        source_kind="wiki",
        retrieved_at="2026-09-13T04:00:00+00:00",
    )
    assert ref.ref_id == "wiki:notes/foo"
    assert ref.title == "foo"
    assert ref.score == 3.5
    assert ref.source_kind == "wiki"
    assert ref.retrieved_at == "2026-09-13T04:00:00+00:00"
    with pytest.raises(FrozenInstanceError):
        ref.score = 9.0  # type: ignore[misc]


def test_mcp_error_and_classifier_are_reexported_not_duplicated() -> None:
    # Same object identity as the ..mcp module -- proves re-export, not a copy.
    assert MCPError is MCPErrorFromMCP
    assert classify_mcp_error is classify_mcp_error_from_mcp


def test_classify_mcp_error_still_covers_the_full_kind_vocabulary() -> None:
    assert classify_mcp_error(TimeoutError("timed out")).kind == "timeout"
    assert classify_mcp_error(ConnectionError("broken pipe")).kind == "disconnect"
    assert classify_mcp_error(ValueError("schema validation failed")).kind == "malformed"
    assert classify_mcp_error(RuntimeError("not supported")).kind == "unsupported_capability"
    assert classify_mcp_error(PermissionError("permission denied")).kind == "permission_denied"
    assert classify_mcp_error(Exception("???")).kind == "unknown"


class _ConformingAdapter:
    def search_evidence(self, query, top_k=5, *, window=None, filters=None):  # noqa: ANN001
        return []

    def read_evidence(self, ref_id, offset=0, limit=2000):  # noqa: ANN001
        return ""


def test_a_conforming_class_satisfies_the_protocol_via_structural_typing() -> None:
    adapter: EvidenceSourceAdapter = _ConformingAdapter()
    assert adapter.search_evidence("q") == []
    assert adapter.read_evidence("x") == ""
