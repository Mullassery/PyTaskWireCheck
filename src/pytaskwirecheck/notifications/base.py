"""Notification interfaces.

Notifications are best-effort observability. A notification failure must never
change a run's outcome, and payloads must never include full environments,
command output, or file contents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol


@dataclass(frozen=True)
class RunNotification:
    """A sanitised, minimal description of a completed run."""

    event: str
    run_id: str
    project: str
    succeeded: bool
    cancelled: bool
    duration_seconds: float
    counts: Dict[str, int] = field(default_factory=dict)
    failed_tasks: List[Dict[str, Optional[object]]] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            "event": self.event,
            "run_id": self.run_id,
            "project": self.project,
            "succeeded": self.succeeded,
            "cancelled": self.cancelled,
            "duration_seconds": round(self.duration_seconds, 4),
            "counts": self.counts,
            "failed_tasks": self.failed_tasks,
        }


class Notifier(Protocol):
    def send(self, notification: RunNotification) -> bool:
        """Deliver a notification; return True on success."""
