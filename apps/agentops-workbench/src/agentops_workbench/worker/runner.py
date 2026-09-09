"""Async run runner — decouples API request from graph execution.

Usage:
    from agentops_workbench.worker.runner import submit_run
    future = submit_run(run_id)  # returns concurrent.futures.Future
    future.result()              # blocks until done
"""
from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor

log = logging.getLogger(__name__)

# A single-thread executor keeps MVP simple. Production: arq + Redis.
_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agentops-worker")
    return _executor


def submit_run(run_id: str) -> Future:
    """Submit a run_id for async execution. Returns a Future.

    The actual graph execution lives in api.server._execute_run.
    This module is a thin shim so the production swap (arq + Redis)
    doesn't require touching the API surface.
    """
    from agentops_workbench.api.server import _execute_run
    log.info("worker: submitting run_id=%s", run_id)
    return _get_executor().submit(_execute_run, run_id)


def shutdown(wait: bool = True) -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait)
        _executor = None
