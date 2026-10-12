"""Task execution state and the task state machine.

Illegal transitions are rejected explicitly so that scheduler bugs surface as
loud errors instead of corrupting run state.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Set

from pytaskwirecheck.diagnostics.errors import ExecutionError


class TaskStatus(str, enum.Enum):
    """Lifecycle states for a single task within a run."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CACHED = "cached"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    BLOCKED = "blocked"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL

    @property
    def is_success(self) -> bool:
        return self in (TaskStatus.SUCCEEDED, TaskStatus.CACHED)

    @property
    def is_failure(self) -> bool:
        return self in (
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
            TaskStatus.BLOCKED,
        )


_TERMINAL: FrozenSet[TaskStatus] = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.SKIPPED,
        TaskStatus.CACHED,
        TaskStatus.CANCELLED,
        TaskStatus.TIMED_OUT,
        TaskStatus.BLOCKED,
    }
)

_ALLOWED_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.READY,
        TaskStatus.BLOCKED,
        TaskStatus.SKIPPED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.READY: {
        TaskStatus.RUNNING,
        TaskStatus.CACHED,
        TaskStatus.SKIPPED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.TIMED_OUT,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
        TaskStatus.CACHED,
    },
}


def is_transition_allowed(old: TaskStatus, new: TaskStatus) -> bool:
    if old is new:
        return True
    if old.is_terminal:
        return False
    return new in _ALLOWED_TRANSITIONS.get(old, set())


def ensure_transition(task_id: str, old: TaskStatus, new: TaskStatus) -> None:
    """Raise :class:`ExecutionError` if the transition is illegal."""
    if not is_transition_allowed(old, new):
        raise ExecutionError(
            "illegal state transition %s -> %s" % (old.value, new.value),
            task=task_id,
        )


@dataclass
class TaskRecord:
    """Mutable per-task runtime state owned by the scheduler."""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    attempt: int = 0
    max_attempts: int = 1
    exit_code: Optional[int] = None
    duration_seconds: float = 0.0
    cache_hit: bool = False
    cache_key: Optional[str] = None
    message: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    output_bytes: int = 0
    history: list = field(default_factory=list)

    def transition(self, new: TaskStatus, *, message: str = "") -> None:
        ensure_transition(self.task_id, self.status, new)
        self.status = new
        if message:
            self.message = message
