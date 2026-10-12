"""Construction of a :class:`~pytaskwirecheck.graph.model.TaskGraph` from config.

Building is a pure transformation. Missing dependency references are recorded
faithfully (as edges to absent nodes) so that
:mod:`pytaskwirecheck.graph.validator` can report them precisely.
"""

from __future__ import annotations

from typing import Dict, List, Set

from pytaskwirecheck.config.schema import WorkflowConfig
from pytaskwirecheck.graph.model import TaskGraph, TaskNode


def build_graph(config: WorkflowConfig) -> TaskGraph:
    """Build the task graph from a validated workflow configuration."""
    known: Set[str] = set(config.tasks.keys())
    dependents: Dict[str, List[str]] = {task_id: [] for task_id in known}

    for task_id, task in config.tasks.items():
        for dependency in task.depends_on:
            if dependency in known:
                dependents[dependency].append(task_id)

    nodes: Dict[str, TaskNode] = {}
    for task_id, task in config.tasks.items():
        nodes[task_id] = TaskNode(
            config=task,
            depends_on=tuple(task.depends_on),
            dependents=tuple(dependents[task_id]),
        )
    return TaskGraph(nodes)
