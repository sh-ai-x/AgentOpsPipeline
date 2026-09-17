"""ADR-0010 step 10: the real fastembed-backed rerank wrapper must convert
raw cross-encoder logits to a 0-1 score.

Caught by actually running `_FastEmbedRerankBackend` against the real model
(see docs/adr/0010 Consequences): `TextCrossEncoder.rerank()` returns raw,
unbounded (often negative) logits, not 0-1 scores -- contradicting the
"0-1, higher = more relevant" contract the UI and ADR document. This test
pins the sigmoid fix without needing the real ~90MB model download: it
monkeypatches `fastembed.rerank.cross_encoder.TextCrossEncoder` with a fake
that returns known logits.
"""
from __future__ import annotations

import math
import sys
import types

import pytest


class _FakeTextCrossEncoder:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        # Deterministic "logits": longer documents score higher, and the
        # first one is deliberately negative to prove negative logits are
        # handled (a raw negative value must not leak out as-is).
        return [-5.0 + len(d) for d in documents]


@pytest.fixture
def _stub_fastembed_cross_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("fastembed.rerank.cross_encoder")
    fake_module.TextCrossEncoder = _FakeTextCrossEncoder  # type: ignore[attr-defined]
    fake_rerank_pkg = types.ModuleType("fastembed.rerank")
    fake_rerank_pkg.cross_encoder = fake_module  # type: ignore[attr-defined]
    fake_fastembed_pkg = sys.modules.get("fastembed") or types.ModuleType("fastembed")
    fake_fastembed_pkg.rerank = fake_rerank_pkg  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", fake_fastembed_pkg)
    monkeypatch.setitem(sys.modules, "fastembed.rerank", fake_rerank_pkg)
    monkeypatch.setitem(sys.modules, "fastembed.rerank.cross_encoder", fake_module)


def test_fastembed_rerank_backend_sigmoids_raw_logits_into_0_1(
    _stub_fastembed_cross_encoder: None,
) -> None:
    from agentops_workbench.adapters.wiki_rag import _FastEmbedRerankBackend

    backend = _FastEmbedRerankBackend(model_name="fake-model")
    scores = backend.rerank("q", ["a", "bb", "ccc"])

    raw_logits = [-5.0 + len(d) for d in ("a", "bb", "ccc")]
    expected = [1.0 / (1.0 + math.exp(-logit)) for logit in raw_logits]

    assert scores == pytest.approx(expected)
    for s in scores:
        assert 0.0 < s < 1.0
    # Monotonic: ranking order must be unaffected by the transform.
    assert scores[0] < scores[1] < scores[2]
