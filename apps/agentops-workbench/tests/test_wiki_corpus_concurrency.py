"""Regression: one slow `register()` build (dense/hybrid mode embedding
every chunk) must not block every OTHER registry operation server-wide.

Real incident: `WikiCorpusRegistry.register()` held its lock for the
entire duration of `build()`, so one operator picking a directory in
`dense`/`hybrid` mode over a large wiki froze `/v1/wiki/index-files`,
`/v1/wiki/search` and `/v1/wiki/qa` for every OTHER session on the same
process until that one embedding job finished -- confirmed live via a
uvicorn worker sitting at 30% CPU for 8+ minutes while a trivial 1-file
tfidf index request queued behind it indefinitely.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from agentops_workbench.adapters.wiki_rag import WikiRagAdapter
from agentops_workbench.wiki_corpus import WikiCorpusRegistry


def _build_stub(tmp_path: Path, name: str) -> tuple:
    work = tmp_path / name
    work.mkdir(exist_ok=True)
    (work / "stub.md").write_text("stub", encoding="utf-8")
    adapter = WikiRagAdapter(wiki_dir=str(work))
    return adapter, work, {"stub": "stub.md"}, {"stub": 0}


def test_a_slow_build_does_not_block_a_concurrent_get_on_another_corpus(
    tmp_path: Path,
) -> None:
    reg = WikiCorpusRegistry(cap=16)
    reg.register("fast", lambda: _build_stub(tmp_path, "fast"))

    build_started = threading.Event()
    release_build = threading.Event()

    def slow_build() -> tuple:
        build_started.set()
        assert release_build.wait(timeout=5), "test setup: release never signaled"
        return _build_stub(tmp_path, "slow")

    slow_thread = threading.Thread(target=lambda: reg.register("slow", slow_build))
    slow_thread.start()
    try:
        assert build_started.wait(timeout=2), "slow build never started"

        t0 = time.monotonic()
        reg.get("fast")  # must NOT wait for the slow build to finish
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, (
            f"get('fast') took {elapsed:.2f}s while an unrelated slow build was "
            "in progress -- the registry lock is serializing unrelated corpora"
        )
    finally:
        release_build.set()
        slow_thread.join(timeout=5)


def test_a_slow_build_does_not_block_a_concurrent_register_of_another_corpus(
    tmp_path: Path,
) -> None:
    reg = WikiCorpusRegistry(cap=16)

    build_started = threading.Event()
    release_build = threading.Event()

    def slow_build() -> tuple:
        build_started.set()
        assert release_build.wait(timeout=5), "test setup: release never signaled"
        return _build_stub(tmp_path, "slow")

    slow_thread = threading.Thread(target=lambda: reg.register("slow", slow_build))
    slow_thread.start()
    try:
        assert build_started.wait(timeout=2), "slow build never started"

        t0 = time.monotonic()
        reg.register("fast", lambda: _build_stub(tmp_path, "fast"))
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, (
            f"register('fast') took {elapsed:.2f}s while an unrelated slow build "
            "was in progress -- the registry lock is serializing unrelated corpora"
        )
        assert "fast" in reg
    finally:
        release_build.set()
        slow_thread.join(timeout=5)


def test_registry_state_is_still_consistent_after_concurrent_registers(
    tmp_path: Path,
) -> None:
    """Narrowing the lock to just the dict mutation must not reintroduce a
    race on the dict itself -- every corpus registered concurrently must
    still be present and independently retrievable afterward."""
    reg = WikiCorpusRegistry(cap=16)
    names = [f"c{i}" for i in range(8)]
    threads = [
        threading.Thread(target=lambda n=n: reg.register(n, lambda n=n: _build_stub(tmp_path, n)))
        for n in names
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(reg) == len(names)
    for n in names:
        assert n in reg
        assert reg.get(n).corpus_id == n
