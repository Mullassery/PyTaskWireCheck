"""Newline-delimited JSON event logging for a run.

This produces a machine-readable trace alongside human output. Task output
events are summarised (never inlined) to avoid unbounded log growth.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from pathlib import Path
from typing import Any, Optional

from pytaskwirecheck.config.loader import state_dir
from pytaskwirecheck.engine.events import Event, TaskOutput


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "value"):  # Enum
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _encode(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    return value


def event_to_dict(event: Event) -> dict:
    payload = _encode(event)
    payload["event"] = type(event).__name__
    return payload


class StructuredLogger:
    """Writes JSONL events to ``.pytaskwirecheck/runs/<run_id>.jsonl``."""

    def __init__(self, root: Path, run_id: str) -> None:
        self._path: Optional[Path] = None
        self._handle = None
        self._lock = threading.Lock()
        try:
            base = state_dir(root) / "runs"
            base.mkdir(parents=True, exist_ok=True)
            self._path = base / ("%s.jsonl" % run_id)
            self._handle = open(self._path, "a", encoding="utf-8")
        except OSError:
            self._handle = None

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def handle(self, event: Event) -> None:
        if self._handle is None:
            return
        if isinstance(event, TaskOutput):
            payload = {
                "event": "TaskOutput",
                "task_id": event.task_id,
                "stream": event.stream,
                "bytes": len(event.data),
            }
        else:
            payload = event_to_dict(event)
        line = json.dumps(payload, separators=(",", ":"), default=str)
        with self._lock:
            try:
                self._handle.write(line + "\n")
                self._handle.flush()
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                try:
                    self._handle.close()
                except OSError:
                    pass
                self._handle = None
