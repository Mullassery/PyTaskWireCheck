"""Graph construction, validation, and planning tests."""

from __future__ import annotations

import pytest

from pytaskwirecheck.diagnostics.errors import CycleError, GraphError
from pytaskwirecheck.graph.builder import build_graph
from pytaskwirecheck.graph.planner import (
    build_plan,
    execution_levels,
    resolve_targets,
    topological_order,
)
from pytaskwirecheck.graph.validator import (
    find_cycle,
    find_missing_dependencies,
    validate_graph,
)

CHAIN = """
[tasks.a]
command = ["true"]
[tasks.b]
command = ["true"]
depends_on = ["a"]
[tasks.c]
command = ["true"]
depends_on = ["b"]
"""

DIAMOND = """
[tasks.root]
command = ["true"]
[tasks.left]
command = ["true"]
depends_on = ["root"]
[tasks.right]
command = ["true"]
depends_on = ["root"]
[tasks.end]
command = ["true"]
depends_on = ["left", "right"]
"""


def _graph(make_config, text):
    return build_graph(make_config(text))


def test_chain_order(make_config):
    graph = _graph(make_config, CHAIN)
    assert topological_order(graph) == ["a", "b", "c"]
    levels = execution_levels(graph)
    assert levels == [["a"], ["b"], ["c"]]


def test_diamond_levels(make_config):
    graph = _graph(make_config, DIAMOND)
    levels = execution_levels(graph)
    assert levels[0] == ["root"]
    assert set(levels[1]) == {"left", "right"}
    assert levels[2] == ["end"]
    plan = build_plan(graph)
    assert plan.max_parallelism == 2


def test_independent_nodes_level0(make_config):
    graph = _graph(
        make_config,
        """
        [tasks.a]
        command = ["true"]
        [tasks.b]
        command = ["true"]
        """,
    )
    assert execution_levels(graph) == [["a", "b"]]


def test_cycle_detected(make_config):
    graph = _graph(
        make_config,
        """
        [tasks.a]
        command = ["true"]
        depends_on = ["c"]
        [tasks.b]
        command = ["true"]
        depends_on = ["a"]
        [tasks.c]
        command = ["true"]
        depends_on = ["b"]
        """,
    )
    cycle = find_cycle(graph)
    assert cycle
    assert cycle[0] == cycle[-1]
    with pytest.raises(CycleError):
        validate_graph(graph)


def test_missing_dependency(make_config):
    graph = _graph(
        make_config,
        """
        [tasks.a]
        command = ["true"]
        depends_on = ["ghost"]
        """,
    )
    missing = find_missing_dependencies(graph)
    assert missing == {"a": ("ghost",)}
    with pytest.raises(GraphError, match="unknown task dependencies"):
        validate_graph(graph)


def test_deterministic_order(make_config):
    graph = _graph(make_config, DIAMOND)
    assert topological_order(graph) == topological_order(graph)
    first = topological_order(graph)
    second = topological_order(build_graph(make_config(DIAMOND)))
    assert first == second


def test_closure_includes_dependencies(make_config):
    graph = _graph(make_config, DIAMOND)
    assert graph.closure(["end"]) == {"root", "left", "right", "end"}


def test_reverse_closure(make_config):
    graph = _graph(make_config, DIAMOND)
    assert graph.reverse_closure(["root"]) == {"root", "left", "right", "end"}


def test_resolve_targets_subset(make_config):
    graph = _graph(make_config, DIAMOND)
    assert resolve_targets(graph, ["left"]) == {"root", "left"}
    assert resolve_targets(graph, []) == {"root", "left", "right", "end"}


def test_resolve_unknown_target(make_config):
    graph = _graph(make_config, DIAMOND)
    with pytest.raises(GraphError, match="unknown task"):
        resolve_targets(graph, ["nope"])


def test_roots_and_leaves(make_config):
    graph = _graph(make_config, DIAMOND)
    assert graph.roots() == ("root",)
    assert graph.leaves() == ("end",)
