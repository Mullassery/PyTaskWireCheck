"""Cancellation signalling shared between the scheduler and process runner."""

from __future__ import annotations

import threading


class CancellationToken:
    """A one-shot cancellation signal with an associated reason.

    The token is safe to share across threads. Once cancelled it stays
    cancelled; retries observe the token and suppress further attempts.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason = ""

    def cancel(self, reason: str = "") -> None:
        with self._lock:
            if not self._reason and reason:
                self._reason = reason
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    @property
    def event(self) -> threading.Event:
        """The underlying event, suitable for passing to the process runner."""
        return self._event
