"""TDD regression - worker shim."""
from __future__ import annotations

from agentops_workbench.worker.runner import shutdown, submit_run


def test_submit_run_returns_future() -> None:
    fut = submit_run("non-existent-run-id")
    assert fut is not None
    result = fut.result(timeout=5)
    assert result is None
    shutdown()


def test_shutdown_is_idempotent() -> None:
    shutdown()
    shutdown()
