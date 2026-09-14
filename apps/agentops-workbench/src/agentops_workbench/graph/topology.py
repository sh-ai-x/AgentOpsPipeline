"""Topology registry — fixed / single_agent / planner_executor under one interface.

Every wrapper returns a dict that ALWAYS includes a `tool_results` key
(possibly empty). This is the contract downstream consumers (e.g. the
held-out runner, the tool-call scoring pipeline) rely on -- so they
never need topology-specific knowledge of which wrappers expose the
key and which don't.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..llm.adapter import LLMAdapter
from .fixed import GraphOutput, run_fixed_graph
from .planner_executor import PlannerExecutorOutput, run_planner_executor
from .single_agent import SingleAgentOutput, run_single_agent


def fixed(adapter: LLMAdapter, task: str) -> dict[str, Any]:
    out: GraphOutput = run_fixed_graph(adapter, task)
    return {"state": out.state, "answer": out.answer, "route": out.route, "tool_results": []}


def single_agent(adapter: LLMAdapter, task: str) -> dict[str, Any]:
    out: SingleAgentOutput = run_single_agent(adapter, task)
    return {
        "state": out.state,
        "answer": out.answer,
        "steps": out.steps,
        "tool_results": out.tool_results,
    }


def planner_executor(adapter: LLMAdapter, task: str) -> dict[str, Any]:
    out: PlannerExecutorOutput = run_planner_executor(adapter, task)
    return {
        "state": out.state,
        "answer": out.answer,
        "plan": out.plan,
        "steps_executed": out.steps_executed,
        "tool_results": out.tool_results,
    }


TOPOLOGIES: dict[str, Callable[[LLMAdapter, str], dict[str, Any]]] = {
    "fixed": fixed,
    "single_agent": single_agent,
    "planner_executor": planner_executor,
}


def run_topology(name: str, adapter: LLMAdapter, task: str) -> dict[str, Any]:
    fn = TOPOLOGIES[name]
    return fn(adapter, task)
