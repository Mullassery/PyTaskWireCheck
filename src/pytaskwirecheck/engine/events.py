"""Execution events and a minimal synchronous event bus.

Events decouple the engine from presentation. Listeners must be fast and must
not raise; the bus isolates listener exceptions so one bad subscriber cannot
corrupt the scheduler.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from pytaskwirecheck.engine.state import TaskStatus


@dataclass
class Event:
    """Base class for all engine events."""


@dataclass
class RunStarted(Event):
    run_id: str
    tasks: tuple
    total_tasks: int


@dataclass
class TaskStateChanged(Event):
    task_id: str
    status: TaskStatus
    message: str = ""


@dataclass
class TaskAttemptStarted(Event):
    task_id: str
    attempt: int
    max_attempts: int


@dataclass
class TaskAttemptFinished(Event):
    task_id: str
    attempt: int
    status: TaskStatus
    exit_code: Optional[int]
    duration_seconds: float


@dataclass
class TaskOutput(Event):
    task_id: str
    stream: str
    data: bytes


@dataclass
class RunFinished(Event):
    run_id: str
    succeeded: bool
    summary: dict = field(default_factory=dict)


Listener = Callable[[Event], None]


class EventBus:
    """A thread-safe, synchronous publish/subscribe bus."""

    def __init__(self) -> None:
        self._listeners: List[Listener] = []
        self._lock = threading.Lock()

    def subscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def emit(self, event: Event) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # Presentation must never break execution.
                continue
