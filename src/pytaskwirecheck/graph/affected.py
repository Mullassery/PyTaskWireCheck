"""Map changed files to affected tasks and their dependents."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Iterable, Set

from pytaskwirecheck.graph.model import TaskGraph


def changed_files(root: Path, since: str = "HEAD~1") -> Set[str]:
    """Return repo-relative paths changed since ``since`` via git."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--name-only",
            "--diff-filter=ACMRTUXB",
            since,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "git diff failed")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _matches(path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        variants = {pattern, pattern.replace("**/", "")}
        if any(
            fnmatch.fnmatch(path, variant) or Path(path).match(variant)
            for variant in variants
        ):
            return True
    return False


def affected_tasks(graph: TaskGraph, changed: Iterable[str]) -> Set[str]:
    """Tasks whose declared inputs match ``changed``, plus all dependents."""
    changed_set = set(changed)
    direct: Set[str] = set()
    for node in graph:
        if node.config.inputs and any(
            _matches(path, node.config.inputs) for path in changed_set
        ):
            direct.add(node.id)

    affected = set(direct)
    queue = list(direct)
    while queue:
        task_id = queue.pop()
        node = graph.get(task_id)
        for dependent in node.dependents:
            if dependent not in affected:
                affected.add(dependent)
                queue.append(dependent)
    return affected
