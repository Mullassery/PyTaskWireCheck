"""HTTP webhook notifications.

The webhook notifier is opt-in and disabled by default. It uses only the
standard library, applies an explicit network timeout, and retries a bounded
number of times with a short delay. Failures are reported as ``False`` (and
optionally as an error string); they never raise into the run.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

from pytaskwirecheck.notifications.base import RunNotification


class WebhookNotifier:
    """Posts run notifications as JSON to a single HTTP endpoint."""

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = 5.0,
        max_attempts: int = 2,
        retry_delay_seconds: float = 0.5,
        events: Tuple[str, ...] = ("failure",),
    ) -> None:
        if not url:
            raise ValueError("webhook url must not be empty")
        self._url = url
        self._timeout = timeout_seconds
        self._max_attempts = max(1, max_attempts)
        self._retry_delay = retry_delay_seconds
        self._events = events
        self.errors: List[str] = []

    def wants(self, event: str) -> bool:
        return event in self._events

    def send(self, notification: RunNotification) -> bool:
        if not self.wants(notification.event):
            return True
        body = json.dumps(notification.to_payload()).encode("utf-8")
        last_error: Optional[str] = None
        for attempt in range(1, self._max_attempts + 1):
            request = urllib.request.Request(
                self._url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    status = getattr(response, "status", 200)
                    if 200 <= status < 300:
                        return True
                    last_error = "HTTP %s" % status
            except urllib.error.URLError as exc:
                # Do not leak response bodies; str(exc) may include the URL.
                last_error = "network error: %s" % exc.reason
            except (TimeoutError, OSError) as exc:
                last_error = "network error: %s" % type(exc).__name__
            if attempt < self._max_attempts:
                time.sleep(self._retry_delay)
        if last_error:
            self.errors.append(last_error)
        return False
