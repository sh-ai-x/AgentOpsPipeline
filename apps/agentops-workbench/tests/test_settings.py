"""ADR-0010 step 11: settings validates AGENTOPS_WIKI_DEFAULT_RETRIEVAL
against the same allow-list WikiRagAdapter enforces, at startup rather than
at first index-files call -- mirrors ADR-0007 §4's "Unknown names fail at
startup" and the existing `_guard_jwt_algorithm` idiom."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentops_workbench.settings import Settings


def test_valid_retrieval_modes_are_accepted() -> None:
    for mode in ("tfidf", "bm25", "dense", "hybrid", "hybrid_rerank"):
        s = Settings(wiki_default_retrieval=mode, jwt_secret="x" * 32)
        assert s.wiki_default_retrieval == mode


def test_unknown_retrieval_mode_fails_at_settings_construction() -> None:
    with pytest.raises(ValidationError, match="AGENTOPS_WIKI_DEFAULT_RETRIEVAL"):
        Settings(wiki_default_retrieval="not-a-real-mode", jwt_secret="x" * 32)


# ---- reasoning_effort (GPT-5-family models via OpenAICompatAdapter) ----


def test_empty_reasoning_effort_is_accepted_as_unset() -> None:
    s = Settings(reasoning_effort="", jwt_secret="x" * 32)
    assert s.reasoning_effort == ""


def test_valid_reasoning_effort_values_are_accepted() -> None:
    for level in ("none", "low", "medium", "high", "xhigh", "max"):
        s = Settings(reasoning_effort=level, jwt_secret="x" * 32)
        assert s.reasoning_effort == level


def test_unknown_reasoning_effort_fails_at_settings_construction() -> None:
    with pytest.raises(ValidationError, match="AGENTOPS_REASONING_EFFORT"):
        Settings(reasoning_effort="ultra-mega", jwt_secret="x" * 32)
