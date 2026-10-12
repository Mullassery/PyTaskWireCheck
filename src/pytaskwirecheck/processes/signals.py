"""Signal handling helpers for graceful cancellation.

PyTaskWireCheck installs temporary handlers so that Ctrl-C (SIGINT) and SIGTERM set a
cancellation event rather than abruptly killing the scheduler. Handlers are
restored on exit to avoid surprising the embedding process.
"""

from __future__ import annotations

import signal
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, List, Optional


@contextmanager
def install_cancel_handlers(
    set_cancel: Callable[[], None],
    *,
    signals: Optional[List[int]] = None,
) -> Iterator[None]:
    """Register handlers that call ``set_cancel`` on interruption.

    On the second signal (an impatient Ctrl-C), the default behaviour is
    restored and the signal is re-raised, so a user can always escape.
    """
    if signals is None:
        signals = [signal.SIGINT, signal.SIGTERM]

    previous: List[tuple] = []
    fired = {"count": 0}

    def _handler(signum: int, frame: object) -> None:  # pragma: no cover
        fired["count"] += 1
        if fired["count"] == 1:
            set_cancel()
            return
        # Second signal: restore defaults and re-raise for a hard exit.
        _restore()
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)

    def _restore() -> None:
        for signum, old in previous:
            try:
                signal.signal(signum, old)
            except (ValueError, OSError):  # pragma: no cover
                pass

    for signum in signals:
        try:
            old = signal.signal(signum, _handler)
            previous.append((signum, old))
        except (ValueError, OSError):
            # Non-main thread or unsupported signal: skip quietly.
            continue
    try:
        yield
    finally:
        _restore()


def new_cancel_event() -> threading.Event:
    return threading.Event()
