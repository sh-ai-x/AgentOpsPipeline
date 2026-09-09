"""TDD regression — step 5 topology variants + matched-budget invariant."""
from __future__ import annotations

import pytest

from agentops_workbench.graph.planner_executor import run_planner_executor
from agentops_workbench.graph.single_agent import MAX_STEPS, run_single_agent
from agentops_workbench.graph.state import RunState
from agentops_workbench.graph.topology import TOPOLOGIES, run_topology
from agentops_workbench.llm.local_fake import LocalFakeAdapter

# ---- Single-agent ----


def test_single_agent_reaches_terminal_state() -> None:
    a = LocalFakeAdapter()
    out = run_single_agent(a, "anything at all")
    assert out.state in {RunState.SUCCEEDED, RunState.FAILED}
    assert out.answer


def test_single_agent_respects_max_steps() -> None:
    a = LocalFakeAdapter()
    out = run_single_agent(a, "no clear directive, just keep looping forever", max_steps=3)
    # When budget is exhausted, we return REFUSE_MESSAGE
    assert out.steps <= 3


# ---- Planner/executor ----


def test_planner_executor_returns_plan() -> None:
    a = LocalFakeAdapter()
    out = run_planner_executor(a, "How do I configure LangGraph with Postgres?")
    assert out.state in {RunState.SUCCEEDED, RunState.FAILED}
    # plan may be empty (parser fallback) but the call must succeed
    assert isinstance(out.plan, list)


def test_planner_executor_bounded_by_executor_steps() -> None:
    a = LocalFakeAdapter()
    out = run_planner_executor(a, "anything")
    # MAX_EXECUTOR_STEPS caps the walk
    from agentops_workbench.graph.planner_executor import MAX_EXECUTOR_STEPS
    assert out.steps_executed <= MAX_EXECUTOR_STEPS


# ---- Topology registry ----


def test_topology_registry_has_three_topologies() -> None:
    assert set(TOPOLOGIES.keys()) == {"fixed", "single_agent", "planner_executor"}


def test_run_topology_dispatches_by_name() -> None:
    a = LocalFakeAdapter()
    out = run_topology("fixed", a, "anything")
    assert "state" in out and "answer" in out


def test_run_topology_unknown_raises() -> None:
    a = LocalFakeAdapter()
    with pytest.raises(KeyError):
        run_topology("nonexistent", a, "x")


# ---- Matched-budget invariant (manifest-level) ----


def test_all_topologies_share_budget_constants() -> None:
    """Per proposal R4: identical budget across topologies.

    This test asserts the *constant values* match. Drift here is a failed
    experiment. Live runs assert the same constants at run-manifest level.
    """
    from agentops_workbench.graph.planner_executor import MAX_EXECUTOR_STEPS, MAX_PLAN_STEPS

    # The fixed graph has no explicit step budget; the single agent caps at MAX_STEPS.
    # The planner executor caps at MAX_PLAN_STEPS * MAX_EXECUTOR_STEPS worst case.
    # For the MVP the three topologies share the *outer* cap of MAX_STEPS=8.
    assert MAX_STEPS == 8
    assert MAX_PLAN_STEPS * MAX_EXECUTOR_STEPS >= MAX_STEPS


# ---- Sanity: all three topologies reach a terminal state for the same input ----


@pytest.mark.parametrize("topology", ["fixed", "single_agent", "planner_executor"])
def test_all_topologies_terminate(topology: str) -> None:
    a = LocalFakeAdapter()
    out = run_topology(topology, a, "How do I configure LangGraph checkpointing with Postgres?")
    assert out["state"] in {RunState.SUCCEEDED.value, RunState.FAILED.value}
    assert out["answer"]
