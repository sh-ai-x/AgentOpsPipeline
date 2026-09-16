"""TDD regression -- wiki_metrics: rolling-window latency + groundedness."""
from __future__ import annotations

from agentops_workbench.wiki_metrics import (
    GroundednessRecorder,
    GroundednessSample,
    StageLatencyRecorder,
    StageSample,
)


def test_stage_latency_p50_and_p95_on_uniform_samples() -> None:
    r = StageLatencyRecorder(window=10)
    # 10 uniform samples: every percentile == 1.0
    for _ in range(10):
        r.record(StageSample(tokenize_ms=1.0, score_ms=1.0, sort_and_return_ms=1.0, total_ms=1.0))
    stats = r.stats()
    for stage in ("tokenize_ms", "score_ms", "sort_and_return_ms", "total_ms"):
        assert stats[stage]["count"] == 10
        assert stats[stage]["p50"] == 1.0
        assert stats[stage]["p95"] == 1.0


def test_stage_latency_p95_exceeds_p50_on_skewed_samples() -> None:
    """Inject 10 ms / 10 ms / 10 ms / ... / 100 ms. p50 ~= 10, p95 ~= 91.5
    (NIST linear-interp percentile). Specifically testing p50 != p95
    so the percentile code is actually computing both, not aliasing."""
    r = StageLatencyRecorder(window=10)
    for ms in [10.0] * 9 + [100.0]:
        r.record(StageSample(tokenize_ms=ms, score_ms=ms, sort_and_return_ms=ms, total_ms=ms))
    s = r.stats()["total_ms"]
    assert s["count"] == 10
    assert s["p50"] < s["p95"], "p50 must be strictly less than p95 on skewed data"
    assert s["p50"] == 10.0
    # Linear interp at p=0.95 across 10 sorted samples: rank = 0.95 * 9 = 8.55
    # 9th sample (lo=8, hi=9) value 100.0 -> 8.55 == 10*0.45 + 100*0.55
    assert abs(s["p95"] - (10.0 * 0.45 + 100.0 * 0.55)) < 0.01


def test_stage_latency_window_eviction_drops_oldest_sample() -> None:
    """WINDOW-sized deque must evict on append. Insert 1001 samples,
    expect count to stop growing at WINDOW=200 (default)."""
    r = StageLatencyRecorder(window=200)
    for i in range(250):
        r.record(StageSample(tokenize_ms=float(i), score_ms=1.0, sort_and_return_ms=1.0, total_ms=1.0))
    s = r.stats()["tokenize_ms"]
    assert s["count"] == 200


def test_stage_latency_reset_for_tests_clears_window() -> None:
    r = StageLatencyRecorder(window=10)
    for _ in range(5):
        r.record(StageSample(1, 1, 1, 1))
    r.reset_for_tests()
    assert r.stats()["total_ms"]["count"] == 0


def test_groundedness_recorder_running_mean() -> None:
    r = GroundednessRecorder(window=4)
    # 4 calls with precision 1.0, recall 0.5, rouge 0.3 -> mean = identity
    for _ in range(4):
        r.record(GroundednessSample(rouge_l_f1=0.3, citation_recall=0.5, citation_precision=1.0))
    s = r.stats()
    assert s["sample_count"] == 4
    assert abs(s["citation_precision_avg"] - 1.0) < 1e-9
    assert abs(s["citation_recall_avg"] - 0.5) < 1e-9
    assert abs(s["rouge_l_f1_avg"] - 0.3) < 1e-9


def test_groundedness_recorder_window_eviction() -> None:
    r = GroundednessRecorder(window=10)
    for _ in range(25):
        r.record(GroundednessSample(rouge_l_f1=0.0, citation_recall=0.0, citation_precision=1.0))
    assert r.stats()["sample_count"] == 10


def test_groundedness_recorder_distinguishes_drift_from_initial_zero() -> None:
    """After filling the window with precision=1.0, then recording 10
    more samples with precision=0.0 (so the entire trailing window is
    0.0), the window's mean must read 0.0 -- the operator watching the
    dashboard sees the drift, not a leftover mix from before.

    Window size is 10; the first 10 (1.0) get evicted by the next 10
    (0.0)."""
    r = GroundednessRecorder(window=10)
    for _ in range(10):
        r.record(GroundednessSample(rouge_l_f1=1.0, citation_recall=1.0, citation_precision=1.0))
    for _ in range(10):
        r.record(GroundednessSample(rouge_l_f1=0.0, citation_recall=0.0, citation_precision=0.0))
    s = r.stats()
    assert s["sample_count"] == 10
    assert s["citation_precision_avg"] == 0.0
    assert s["rouge_l_f1_avg"] == 0.0
