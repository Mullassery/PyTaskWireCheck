"""Error types used across PyTaskWireCheck.

Every error carries enough context to diagnose the failure. Errors that relate
to a specific task include the task identifier; errors that relate to a
configuration location include a best-effort location string.
"""

from __future__ import annotations

from typing import Optional


class PyTaskWireCheckError(Exception):
    """Base class for all PyTaskWireCheck errors.

    Attributes:
        message: Human-readable explanation of the failure.
        task: Optional task identifier the error relates to.
        location: Optional configuration location (e.g. ``tasks.test.inputs``).
    """

    def __init__(
        self,
        message: str,
        *,
        task: Optional[str] = None,
        location: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.task = task
        self.location = location

    def __str__(self) -> str:
        parts = []
        if self.task:
            parts.append("task '%s'" % self.task)
        if self.location:
            parts.append("at %s" % self.location)
        prefix = (" (" + ", ".join(parts) + ")") if parts else ""
        return self.message + prefix


class ConfigError(PyTaskWireCheckError):
    """Raised when the configuration file is malformed or invalid."""


class ConfigVersionError(ConfigError):
    """Raised when the configuration declares an unsupported version."""


class GraphError(PyTaskWireCheckError):
    """Raised when the task graph is invalid (e.g. cycles, missing deps)."""


class CycleError(GraphError):
    """Raised when the task graph contains a dependency cycle.

    Attributes:
        cycle: The ordered cycle path, repeating the first node at the end.
    """

    def __init__(self, cycle: list) -> None:
        self.cycle = list(cycle)
        rendered = " -> ".join(self.cycle)
        super().__init__("dependency cycle detected: %s" % rendered)


class ExecutionError(PyTaskWireCheckError):
    """Raised for failures in the execution engine itself (not task failures)."""


class ProcessStartError(ExecutionError):
    """Raised when a subprocess cannot be started (missing binary, perms, ...)."""


class CacheError(PyTaskWireCheckError):
    """Raised for cache storage or integrity failures."""


class HistoryError(PyTaskWireCheckError):
    """Raised for execution history persistence failures."""


class NotificationError(PyTaskWireCheckError):
    """Raised for notification delivery failures."""
