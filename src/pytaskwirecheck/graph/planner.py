"""Topological planning for the task graph.

The planner produces deterministic orderings and parallelism opportunities. It
is pure: it never launches processes, touches the cache, or renders output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from pytaskwirecheck.diagnostics.errors import GraphError
from pytaskwirecheck.graph.model import TaskGraph


@dataclass(frozen=True)
class PlannedTask:
    """A task as it appears in a plan."""

    id: str
    dependencies: Tuple[str, ...]
    level: int
    cache_eligible: bool


@dataclass(frozen=True)
class ExecutionPlan:
    """A deterministic execution plan for a (sub)set of tasks."""

    order: Tuple[str, ...]
    levels: Tuple[Tuple[str, ...], ...]
    tasks: Tuple[PlannedTask, ...]

    @property
    def max_parallelism(self) -> int:
        return max((len(level) for level in self.levels), default=0)


def _ordered_ids(graph: TaskGraph, subset: Optional[Set[str]]) -> List[str]:
    ids = [node.id for node in graph]
    if subset is None:
        return ids
    return [task_id for task_id in ids if task_id in subset]


def topological_order(graph: TaskGraph, subset: Optional[Set[str]] = None) -> List[str]:
    """Return a deterministic topological order of the selected tasks.

    Ties are broken by declaration order, so the same configuration always
    yields the same plan.

    Raises:
        GraphError: if the selected subgraph contains a cycle.
    """
    ordered = _ordered_ids(graph, subset)
    selected = set(ordered)
    rank = {task_id: index for index, task_id in enumerate(ordered)}

    indegree: Dict[str, int] = {}
    for task_id in ordered:
        deps = [d for d in graph.dependencies(task_id) if d in selected]
        indegree[task_id] = len(deps)

    ready: List[str] = sorted(
        (t for t in ordered if indegree[t] == 0), key=rank.__getitem__
    )
    result: List[str] = []
    while ready:
        current = ready.pop(0)
        result.append(current)
        newly_ready: List[str] = []
        for dependent in graph.dependents(current):
            if dependent not in selected:
                continue
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                newly_ready.append(dependent)
        if newly_ready:
            ready.extend(newly_ready)
            ready.sort(key=rank.__getitem__)

    if len(result) != len(ordered):
        raise GraphError("cycle detected while planning")
    return result


def execution_levels(
    graph: TaskGraph, subset: Optional[Set[str]] = None
) -> List[List[str]]:
    """Group selected tasks into levels that may run in parallel.

    Level 0 contains tasks with no selected dependencies; each subsequent level
    contains tasks whose dependencies all live in earlier levels.
    """
    ordered = _ordered_ids(graph, subset)
    selected = set(ordered)
    level_of: Dict[str, int] = {}
    levels: List[List[str]] = []
    for task_id in topological_order(graph, subset):
        deps = [d for d in graph.dependencies(task_id) if d in selected]
        level = 0
        if deps:
            level = max(level_of[d] for d in deps) + 1
        level_of[task_id] = level
        while len(levels) <= level:
            levels.append([])
        levels[level].append(task_id)
    return levels


def build_plan(graph: TaskGraph, subset: Optional[Set[str]] = None) -> ExecutionPlan:
    """Build a full :class:`ExecutionPlan` for the selected tasks."""
    order = topological_order(graph, subset)
    levels = execution_levels(graph, subset)
    level_of: Dict[str, int] = {}
    for index, level in enumerate(levels):
        for task_id in level:
            level_of[task_id] = index

    def sort_key(task_id: str) -> int:
        return order.index(task_id)

    tasks = tuple(
        PlannedTask(
            id=task_id,
            dependencies=tuple(
                d for d in graph.dependencies(task_id) if d in set(order)
            ),
            level=level_of[task_id],
            cache_eligible=graph.get(task_id).config.cache_eligible,
        )
        for task_id in order
    )
    normalized_levels = tuple(tuple(sorted(level, key=sort_key)) for level in levels)
    return ExecutionPlan(order=tuple(order), levels=normalized_levels, tasks=tasks)


def resolve_targets(
    graph: TaskGraph, targets: Sequence[str], *, include_dependents: bool = False
) -> Set[str]:
    """Resolve the set of tasks to run for the given target names.

    With no targets, the entire graph is selected. Otherwise the dependency
    closure of the targets is selected, and optionally every task that depends
    on them.
    """
    if not targets:
        return set(graph.nodes.keys())
    for target in targets:
        if target not in graph.nodes:
            raise GraphError("unknown task: %s" % target, task=target)
    selected = graph.closure(list(targets))
    if include_dependents:
        selected |= graph.reverse_closure(list(targets))
    return selected
