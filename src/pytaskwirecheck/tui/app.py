"""A minimal live terminal dashboard.

Design constraints (from the specification):

* Rendering must never block the scheduler. Events only mutate an in-memory
  snapshot under a lock; a separate daemon thread redraws at a fixed interval.
* It must degrade safely: when the target stream is not a TTY it does nothing.
* Redraws use cursor-home + clear-to-end so they do not scroll task logs away.
* The core engine never imports this module; it is an optional listener.
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, TextIO

from pytaskwirecheck.engine.events import (
    Event,
    RunFinished,
    RunStarted,
    TaskStateChanged,
)
from pytaskwirecheck.engine.state import TaskStatus

_HEAVY = TaskStatus.RUNNING
_CLEAR = "\033[2J"
_HOME = "\033[H"

_SYMBOL = {
    TaskStatus.PENDING: "·",
    TaskStatus.READY: "·",
    TaskStatus.RUNNING: "▶",
    TaskStatus.SUCCEEDED: "✓",
    TaskStatus.CACHED: "✓",
    TaskStatus.FAILED: "✗",
    TaskStatus.TIMED_OUT: "✗",
    TaskStatus.BLOCKED: "✗",
    TaskStatus.CANCELLED: "⊘",
    TaskStatus.SKIPPED: "⊘",
}


@dataclass
class _TaskView:
    status: TaskStatus = TaskStatus.PENDING
    attempt: int = 1
    max_attempts: int = 1
    message: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class _Snapshot:
    run_id: str = ""
    total: int = 0
    started_at: float = field(default_factory=time.monotonic)
    tasks: Dict[str, _TaskView] = field(default_factory=dict)
    finished: bool = False
    succeeded: bool = False


class LiveDashboard:
    """A thread-safe, event-driven terminal dashboard."""

    def __init__(
        self,
        stream: Optional[TextIO] = None,
        *,
        refresh_interval: float = 0.2,
        color: bool = False,
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._interval = max(0.05, refresh_interval)
        self._snapshot = _Snapshot()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._color = color
        self._enabled = False

    # -- listener interface -------------------------------------------------

    def handle(self, event: Event) -> None:
        with self._lock:
            if isinstance(event, RunStarted):
                self._snapshot = _Snapshot(
                    run_id=event.run_id,
                    total=event.total_tasks,
                    started_at=time.monotonic(),
                )
                self._snapshot.tasks = {task_id: _TaskView() for task_id in event.tasks}
            elif isinstance(event, TaskStateChanged):
                view = self._snapshot.tasks.get(event.task_id, _TaskView())
                now = time.monotonic()
                if event.status is TaskStatus.RUNNING and view.started_at is None:
                    view.started_at = now
                if event.status.is_terminal:
                    view.finished_at = now
                view.status = event.status
                if event.message:
                    view.message = event.message
                self._snapshot.tasks[event.task_id] = view
            elif isinstance(event, RunFinished):
                self._snapshot.finished = True
                self._snapshot.succeeded = event.succeeded

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        try:
            self._enabled = bool(self._stream.isatty())
        except (ValueError, AttributeError):
            self._enabled = False
        if not self._enabled:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._enabled:
            self._write(self._render())
            self._write("\n")

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._write(_HOME + self._render())
            except (BrokenPipeError, ValueError):
                return

    # -- rendering ----------------------------------------------------------

    def _counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for view in self._snapshot.tasks.values():
            counts[view.status.value] = counts.get(view.status.value, 0) + 1
        return counts

    def _render(self) -> str:
        with self._lock:
            snapshot = self._snapshot
            total = snapshot.total
            done = sum(1 for view in snapshot.tasks.values() if view.status.is_terminal)
            elapsed = time.monotonic() - snapshot.started_at
            counts = self._counts()
            tasks = sorted(
                snapshot.tasks.items(),
                key=lambda item: (item[1].status.value, item[0]),
            )
            run_id = snapshot.run_id

        columns, lines = shutil.get_terminal_size((80, 24))
        header = "PyTaskWireCheck  run %s   %d/%d done   %6.1fs" % (
            run_id,
            done,
            total,
            elapsed,
        )
        count_line = "  ".join("%d %s" % (counts[key], key) for key in sorted(counts))
        rows = [
            header[:columns],
            count_line[:columns],
            "",
        ]
        available = max(1, lines - len(rows) - 1)
        for task_id, view in tasks:
            if len(rows) >= available + 3:
                rows.append("  ... (%d more)" % (len(tasks) - (len(rows) - 3)))
                break
            symbol = _SYMBOL.get(view.status, "?")
            duration = ""
            if view.started_at is not None:
                end = view.finished_at or time.monotonic()
                duration = "%5.1fs" % (end - view.started_at)
            attempt = (
                " (%d/%d)" % (view.attempt, view.max_attempts)
                if view.max_attempts > 1
                else ""
            )
            suffix = ""
            if view.message and view.status.is_failure:
                suffix = "  %s" % view.message
            rows.append(
                "  %s %-24s %8s%s%s" % (symbol, task_id, duration, attempt, suffix)
            )
        rows.append("")
        return _CLEAR + "\n".join(row[:columns] for row in rows)

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except (BrokenPipeError, ValueError):
            pass
