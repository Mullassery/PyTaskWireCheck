"""Validation of task graphs: missing dependencies and cycles.

Validation is read-only and never executes tasks. It raises
:class:`~pytaskwirecheck.diagnostics.errors.GraphError` subclasses with precise,
actionable messages.
"""

from __future__ import annotations

from typing import Dict, Iterator, List, Tuple

from pytaskwirecheck.diagnostics.errors import CycleError, GraphError
from pytaskwirecheck.graph.model import TaskGraph

_WHITE = 0
_GRAY = 1
_BLACK = 2


def find_missing_dependencies(graph: TaskGraph) -> Dict[str, Tuple[str, ...]]:
    """Return a mapping of task id -> missing dependency ids."""
    known = set(graph.nodes.keys())
    missing: Dict[str, List[str]] = {}
    for node in graph:
        bad = [dep for dep in node.depends_on if dep not in known]
        if bad:
            missing[node.id] = bad
    return {k: tuple(v) for k, v in missing.items()}


def validate_references(graph: TaskGraph) -> None:
    """Raise if any task references a dependency that does not exist."""
    missing = find_missing_dependencies(graph)
    if missing:
        details = "; ".join(
            "%s -> %s" % (task, ", ".join(deps))
            for task, deps in sorted(missing.items())
        )
        first_task = sorted(missing.keys())[0]
        raise GraphError("unknown task dependencies: %s" % details, task=first_task)


def find_cycle(graph: TaskGraph) -> List[str]:
    """Return one dependency cycle as an ordered path, or ``[]`` if acyclic.

    The returned path repeats the first node at the end, e.g.
    ``["a", "b", "c", "a"]``.
    """
    known = set(graph.nodes.keys())
    color: Dict[str, int] = {task_id: _WHITE for task_id in known}

    def deps_iter(task_id: str) -> Iterator[str]:
        return iter(d for d in graph.dependencies(task_id) if d in known)

    for start in known:
        if color[start] != _WHITE:
            continue
        color[start] = _GRAY
        path: List[str] = [start]
        stack: List[Tuple[str, Iterator[str]]] = [(start, deps_iter(start))]
        while stack:
            node, iterator = stack[-1]
            advanced = False
            for dep in iterator:
                if color[dep] == _GRAY:
                    index = path.index(dep)
                    return path[index:] + [dep]
                if color[dep] == _WHITE:
                    color[dep] = _GRAY
                    path.append(dep)
                    stack.append((dep, deps_iter(dep)))
                    advanced = True
                    break
            if not advanced:
                color[node] = _BLACK
                stack.pop()
                if path and path[-1] == node:
                    path.pop()
    return []


def validate_acyclic(graph: TaskGraph) -> None:
    """Raise :class:`CycleError` if the graph contains a cycle."""
    cycle = find_cycle(graph)
    if cycle:
        raise CycleError(cycle)


def validate_graph(graph: TaskGraph) -> None:
    """Run all structural validations against a graph."""
    validate_references(graph)
    validate_acyclic(graph)
