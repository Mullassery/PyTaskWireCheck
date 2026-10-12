"""The task DAG model.

The graph is an immutable structure describing which tasks exist and how they
depend on one another. It contains no scheduling or execution logic; see
:mod:`pytaskwirecheck.graph.planner` for ordering and :mod:`pytaskwirecheck.engine` for
execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, List, Mapping, Set, Tuple

from pytaskwirecheck.config.schema import TaskConfig


@dataclass(frozen=True)
class TaskNode:
    """A single node in the task graph."""

    config: TaskConfig
    depends_on: Tuple[str, ...]
    dependents: Tuple[str, ...]

    @property
    def id(self) -> str:
        return self.config.id


class TaskGraph:
    """An immutable directed acyclic graph of tasks.

    Edges point from a dependency to its dependents (i.e. ``depends_on`` edges
    are stored reversed for efficient ready-task computation).
    """

    def __init__(self, nodes: Mapping[str, TaskNode]) -> None:
        self._nodes: Dict[str, TaskNode] = dict(nodes)

    def __contains__(self, task_id: object) -> bool:
        return task_id in self._nodes

    def __iter__(self) -> Iterator[TaskNode]:
        return iter(self._nodes.values())

    def __len__(self) -> int:
        return len(self._nodes)

    @property
    def nodes(self) -> Mapping[str, TaskNode]:
        return self._nodes

    def get(self, task_id: str) -> TaskNode:
        return self._nodes[task_id]

    def dependencies(self, task_id: str) -> Tuple[str, ...]:
        return self._nodes[task_id].depends_on

    def dependents(self, task_id: str) -> Tuple[str, ...]:
        return self._nodes[task_id].dependents

    def roots(self) -> Tuple[str, ...]:
        """Tasks with no dependencies, in stable declaration order."""
        return tuple(node.id for node in self._nodes.values() if not node.depends_on)

    def leaves(self) -> Tuple[str, ...]:
        """Tasks that nothing depends on, in stable declaration order."""
        return tuple(node.id for node in self._nodes.values() if not node.dependents)

    def closure(self, targets: List[str]) -> Set[str]:
        """Return ``targets`` plus every transitive dependency.

        Raises:
            KeyError: if a target is not present in the graph.
        """
        seen: Set[str] = set()
        stack: List[str] = []
        for target in targets:
            if target not in self._nodes:
                raise KeyError(target)
            stack.append(target)
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for dep in self._nodes[current].depends_on:
                if dep in self._nodes and dep not in seen:
                    stack.append(dep)
        return seen

    def reverse_closure(self, targets: List[str]) -> Set[str]:
        """Return ``targets`` plus every transitive dependent."""
        seen: Set[str] = set()
        stack: List[str] = [t for t in targets if t in self._nodes]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for dep in self._nodes[current].dependents:
                if dep not in seen:
                    stack.append(dep)
        return seen
