"""Run state machine: queued -> running -> waiting_for_approval -> succeeded/failed/cancelled.

Per proposal:
- Cancellation stops future work and reports already-completed actions
  It does NOT imply rollback of external effects
- Approval binds user, run, tool, canonical arguments, expiry, one-use nonce
- Tool calls use stable action keys; after a crash following dispatch,
  query the mock ledger before retrying
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class RunState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Allowed transitions (a state machine, not just an enum).
ALLOWED: dict[RunState, set[RunState]] = {
    RunState.QUEUED: {RunState.RUNNING, RunState.CANCELLED, RunState.FAILED},
    RunState.RUNNING: {
        RunState.WAITING_FOR_APPROVAL,
        RunState.SUCCEEDED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.WAITING_FOR_APPROVAL: {
        RunState.RUNNING,
        RunState.SUCCEEDED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.SUCCEEDED: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}


class StateTransitionError(RuntimeError):
    pass


def can_transition(current: RunState, target: RunState) -> bool:
    return target in ALLOWED.get(current, set())


def assert_transition(current: RunState, target: RunState) -> None:
    if not can_transition(current, target):
        raise StateTransitionError(
            f"illegal transition {current.value} -> {target.value}"
        )


def is_terminal(state: RunState) -> bool:
    return state in {RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED}


def canonical_args_hash(args: dict[str, Any]) -> str:
    """Stable hash of canonical args for action_key dedup."""
    import hashlib
    import json

    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def make_action_key(run_id: str, tool_name: str, args: dict[str, Any]) -> str:
    return f"{run_id}:{tool_name}:{canonical_args_hash(args)}"
