"""Topology registry — fixed / single_agent / planner_executor under one interface."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..llm.adapter import LLMAdapter
from ..settings import DEFAULT_CORPUS_DIR
from .fixed import GraphOutput, run_fixed_graph
from .planner_executor import PlannerExecutorOutput, run_planner_executor
from .single_agent import SingleAgentOutput, run_single_agent


def fixed(
    adapter: LLMAdapter, task: str, *, corpus_dir: str = DEFAULT_CORPUS_DIR, wiki_mode: bool = False
) -> dict[str, Any]:
    # The fixed graph uses _retrieve_docs() (lexical substring scan) regardless
    # of corpus_dir/wiki_mode — wiki_mode is accepted for signature parity
    # but not consulted here. Per-run override is handled by server.py
    # before run_topology is called.
    out: GraphOutput = run_fixed_graph(adapter, task, docs_dir=corpus_dir)
    return {"state": out.state, "answer": out.answer, "route": out.route, "tool_results": []}


def single_agent(
    adapter: LLMAdapter, task: str, *, corpus_dir: str = DEFAULT_CORPUS_DIR, wiki_mode: bool = False
) -> dict[str, Any]:
    out: SingleAgentOutput = run_single_agent(adapter, task, corpus_dir=corpus_dir, wiki_mode=wiki_mode)
    return {
        "state": out.state,
        "answer": out.answer,
        "steps": out.steps,
        "tool_results": out.tool_results,
    }


def planner_executor(
    adapter: LLMAdapter, task: str, *, corpus_dir: str = DEFAULT_CORPUS_DIR, wiki_mode: bool = False
) -> dict[str, Any]:
    out: PlannerExecutorOutput = run_planner_executor(
        adapter, task, corpus_dir=corpus_dir, wiki_mode=wiki_mode
    )
    return {
        "state": out.state,
        "answer": out.answer,
        "plan": out.plan,
        "steps_executed": out.steps_executed,
        "tool_results": out.tool_results,
    }


TOPOLOGIES: dict[str, Callable[..., dict[str, Any]]] = {
    "fixed": fixed,
    "single_agent": single_agent,
    "planner_executor": planner_executor,
}


def run_topology(
    name: str,
    adapter: LLMAdapter,
    task: str,
    *,
    corpus_dir: str = DEFAULT_CORPUS_DIR,
    wiki_mode: bool = False,
) -> dict[str, Any]:
    fn = TOPOLOGIES[name]
    return fn(adapter, task, corpus_dir=corpus_dir, wiki_mode=wiki_mode)
