"""Streaming task output artifacts.

Output is appended to per-task files under the state directory as it is
produced. Writes are bounded so a runaway process cannot exhaust disk during a
run; truncation is recorded in the log.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Dict, Optional

from pytaskwirecheck.config.loader import state_dir
from pytaskwirecheck.engine.events import Event, TaskOutput


@dataclass
class _TaskLog:
    handle: Optional[BinaryIO] = None
    path: Optional[Path] = None
    written: int = 0
    truncated: bool = False


class ArtifactWriter:
    """Persists streamed task output to files, bounded per task."""

    def __init__(
        self,
        root: Path,
        run_id: str,
        *,
        max_bytes_per_task: Optional[int] = 64 * 1024 * 1024,
    ) -> None:
        self._base = state_dir(root) / "logs" / run_id
        self._max_bytes = max_bytes_per_task
        self._lock = threading.Lock()
        self._logs: Dict[str, _TaskLog] = {}

    def _open(self, task_id: str) -> _TaskLog:
        log = self._logs.get(task_id)
        if log is not None:
            return log
        log = _TaskLog()
        try:
            self._base.mkdir(parents=True, exist_ok=True)
            path = self._base / ("%s.log" % task_id)
            log.handle = open(path, "ab")
            log.path = path
        except OSError:
            log.handle = None
        self._logs[task_id] = log
        return log

    def path_for(self, task_id: str) -> Optional[Path]:
        log = self._logs.get(task_id)
        return log.path if log else None

    def handle(self, event: Event) -> None:
        if not isinstance(event, TaskOutput):
            return
        with self._lock:
            log = self._open(event.task_id)
            if log.handle is None or log.truncated:
                return
            data = event.data
            if self._max_bytes is not None:
                remaining = self._max_bytes - log.written
                if remaining <= 0:
                    log.truncated = True
                    try:
                        log.handle.write(b"\n[pytaskwirecheck] output truncated\n")
                    except OSError:
                        pass
                    return
                if len(data) > remaining:
                    data = data[:remaining]
                    log.truncated = True
            try:
                log.handle.write(data)
                log.written += len(data)
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            for log in self._logs.values():
                if log.handle is not None:
                    try:
                        log.handle.close()
                    except OSError:
                        pass
                    log.handle = None
