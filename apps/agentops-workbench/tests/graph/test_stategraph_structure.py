"""Structural tests: prove each topology's internals are a real
`langgraph.graph.StateGraph`, not plain-Python if/else + for-loops.

These assert against the *compiled graph object* (`.get_graph()` ->
nodes/edges), which the old plain-Python implementation cannot satisfy no
matter what answer text it produces. They are the RED step of the TDD
cycle for the StateGraph rewrite.
"""
from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph


def _edge_set(compiled: CompiledStateGraph) -> set[tuple[str, str]]:
    g = compiled.get_graph()
    return {(e.source, e.target) for e in g.edges}


def _conditional_edge_set(compiled: CompiledStateGraph) -> set[tuple[str, str]]:
    g = compiled.get_graph()
    return {(e.source, e.target) for e in g.edges if e.conditional}


# ---- fixed.py: refuse-check / clarify-check / route-answer ----


def test_fixed_graph_is_compiled_stategraph() -> None:
    from agentops_workbench.graph.fixed import _build_graph

    compiled = _build_graph()
    assert isinstance(compiled, CompiledStateGraph)


def test_fixed_graph_has_classify_refuse_clarify_answer_nodes() -> None:
    from agentops_workbench.graph.fixed import _build_graph

    nodes = set(_build_graph().get_graph().nodes)
    assert {"classify", "refuse", "clarify", "answer"} <= nodes


def test_fixed_graph_routes_conditionally_from_classify() -> None:
    from agentops_workbench.graph.fixed import _build_graph

    conditional = _conditional_edge_set(_build_graph())
    assert ("classify", "refuse") in conditional
    assert ("classify", "clarify") in conditional
    assert ("classify", "answer") in conditional


# ---- single_agent.py: loop node with conditional self-edge ----


def test_single_agent_graph_is_compiled_stategraph() -> None:
    from agentops_workbench.graph.single_agent import _build_graph

    compiled = _build_graph()
    assert isinstance(compiled, CompiledStateGraph)


def test_single_agent_graph_has_self_loop_on_step_node() -> None:
    from agentops_workbench.graph.single_agent import _build_graph

    conditional = _conditional_edge_set(_build_graph())
    # A genuine loop: the step node has a conditional edge back to itself.
    self_loops = {(s, t) for s, t in conditional if s == t}
    assert self_loops, f"expected a self-loop edge, got conditional edges={conditional}"


def test_single_agent_graph_has_budget_exhausted_path() -> None:
    from agentops_workbench.graph.single_agent import _build_graph

    nodes = set(_build_graph().get_graph().nodes)
    assert "budget_exhausted" in nodes


# ---- planner_executor.py: plan -> execute (looping) -> synthesize ----


def test_planner_executor_graph_is_compiled_stategraph() -> None:
    from agentops_workbench.graph.planner_executor import _build_graph

    compiled = _build_graph()
    assert isinstance(compiled, CompiledStateGraph)


def test_planner_executor_graph_has_plan_execute_synthesize_nodes() -> None:
    from agentops_workbench.graph.planner_executor import _build_graph

    nodes = set(_build_graph().get_graph().nodes)
    assert {"plan", "execute", "synthesize"} <= nodes


def test_planner_executor_graph_execute_node_has_self_loop() -> None:
    from agentops_workbench.graph.planner_executor import _build_graph

    conditional = _conditional_edge_set(_build_graph())
    self_loops = {(s, t) for s, t in conditional if s == t}
    assert self_loops, f"expected a self-loop edge on execute, got conditional edges={conditional}"


def test_planner_executor_graph_execute_reaches_synthesize_conditionally() -> None:
    from agentops_workbench.graph.planner_executor import _build_graph

    conditional = _conditional_edge_set(_build_graph())
    assert ("execute", "synthesize") in conditional
