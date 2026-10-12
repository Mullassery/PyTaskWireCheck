"""Plain-text console reporting.

This renderer provides a useful non-TTY fallback and a CI-friendly mode. It
never assumes ANSI colour support and keeps concurrent task output labelled.
It only observes events; it never mutates run state.
"""

from __future__ import annotations

import sys
from typing import Dict, Optional, TextIO

from pytaskwirecheck.engine.events import (
    Event,
    RunFinished,
    RunStarted,
    TaskAttemptFinished,
    TaskAttemptStarted,
    TaskOutput,
    TaskStateChanged,
)
from pytaskwirecheck.engine.state import TaskStatus

_STATUS_GLYPH = {
    TaskStatus.SUCCEEDED: "ok",
    TaskStatus.FAILED: "fail",
    TaskStatus.CACHED: "cached",
    TaskStatus.SKIPPED: "skip",
    TaskStatus.CANCELLED: "cancel",
    TaskStatus.TIMED_OUT: "timeout",
    TaskStatus.BLOCKED: "blocked",
}

_COLORS = {
    TaskStatus.SUCCEEDED: "\033[32m",
    TaskStatus.CACHED: "\033[36m",
    TaskStatus.FAILED: "\033[31m",
    TaskStatus.TIMED_OUT: "\033[31m",
    TaskStatus.BLOCKED: "\033[31m",
    TaskStatus.CANCELLED: "\033[33m",
}
_RESET = "\033[0m"


class PlainReporter:
    """A synchronous, line-oriented event reporter."""

    def __init__(
        self,
        stream: Optional[TextIO] = None,
        *,
        color: bool = False,
        quiet: bool = False,
        show_output: bool = True,
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._color = color
        self._quiet = quiet
        self._show_output = show_output
        self._buffers: Dict[tuple, str] = {}

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except (BrokenPipeError, ValueError):
            pass

    def _paint(self, status: TaskStatus, text: str) -> str:
        if not self._color:
            return text
        color = _COLORS.get(status)
        return "%s%s%s" % (color, text, _RESET) if color else text

    def handle(self, event: Event) -> None:
        if isinstance(event, RunStarted):
            if not self._quiet:
                self._write("Run %s: %d task(s)\n" % (event.run_id, event.total_tasks))
            return

        if isinstance(event, TaskAttemptStarted):
            if event.max_attempts > 1 and not self._quiet:
                self._write(
                    "  %s: attempt %d/%d\n"
                    % (event.task_id, event.attempt, event.max_attempts)
                )
            return

        if isinstance(event, TaskAttemptFinished):
            return

        if isinstance(event, TaskStateChanged):
            self._on_state_changed(event)
            return

        if isinstance(event, TaskOutput):
            self._on_output(event)
            return

        if isinstance(event, RunFinished):
            self._on_run_finished(event)
            return

    def _on_state_changed(self, event: TaskStateChanged) -> None:
        if event.status is TaskStatus.RUNNING:
            if not self._quiet and not self._show_output:
                self._write("  %s: running\n" % event.task_id)
            return
        if not event.status.is_terminal:
            return
        glyph = _STATUS_GLYPH.get(event.status, event.status.value)
        suffix = ""
        if event.status is TaskStatus.FAILED and event.message:
            suffix = " (%s)" % event.message
        elif event.status in (TaskStatus.TIMED_OUT, TaskStatus.BLOCKED):
            if event.message:
                suffix = " (%s)" % event.message
        label = self._paint(event.status, glyph)
        self._write("  [%s] %s%s\n" % (label, event.task_id, suffix))

    def _on_output(self, event: TaskOutput) -> None:
        if not self._show_output or self._quiet:
            return
        key = (event.task_id, event.stream)
        buffer = self._buffers.get(key, "")
        buffer += event.data.decode("utf-8", errors="replace")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            prefix = event.task_id
            if event.stream == "stderr":
                prefix += "!stderr"
            self._write("  %s | %s\n" % (prefix, line))
        self._buffers[key] = buffer

    def _on_run_finished(self, event: RunFinished) -> None:
        summary = event.summary or {}
        counts = summary.get("counts", {})
        duration = summary.get("duration_seconds", 0.0)
        status = "succeeded" if event.succeeded else "failed"
        rendered = ", ".join("%d %s" % (counts[k], k) for k in sorted(counts))
        self._write(
            "Run %s %s in %.2fs (%s)\n" % (event.run_id, status, duration, rendered)
        )
