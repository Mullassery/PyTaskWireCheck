"""Subprocess lifecycle management.

This module runs a single configured command and reports its outcome. It has no
knowledge of the DAG, scheduling, caching, or presentation. It is responsible
for correctness under cancellation, timeouts, large output, and start-up
failures.

Design notes:

* Commands are executed as argument arrays. Shell execution is opt-in and
  explicit (``shell=True`` requires a single-element ``argv``).
* Output is streamed to a callback from dedicated reader threads, which avoids
  the classic pipe-buffer deadlock and keeps memory bounded.
* On POSIX, each command runs in its own session/process group so that the
  whole descendant tree can be signalled. On Windows a new process group is
  created and descendants are terminated best-effort.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple, Union

from pytaskwirecheck.diagnostics.errors import ProcessStartError

#: Signature for streaming consumers: (stream_name, chunk) where stream_name is
#: ``"stdout"`` or ``"stderr"``.
OutputCallback = Callable[[str, bytes], None]

_POLL_INTERVAL = 0.05
_GRACE_PERIOD_SECONDS = 5.0
_READ_CHUNK = 65536

_IS_WINDOWS = sys.platform.startswith("win")


@dataclass(frozen=True)
class CommandSpec:
    """Everything needed to run one command."""

    argv: Tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    shell: bool = False
    timeout_seconds: Optional[float] = None
    max_output_bytes: Optional[int] = None


@dataclass
class ProcessResult:
    """The outcome of a single command execution."""

    exit_code: Optional[int]
    timed_out: bool = False
    cancelled: bool = False
    duration_seconds: float = 0.0
    output_bytes: int = 0
    output_truncated: bool = False
    start_error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return (
            self.start_error is None
            and not self.timed_out
            and not self.cancelled
            and self.exit_code == 0
        )


class _OutputSink:
    """Thread-safe, optionally size-bounded output accumulator.

    The sink forwards every chunk to the consumer callback immediately; the
    byte counter is only used to enforce ``max_output_bytes`` once the limit is
    reached (further bytes are dropped from *recording* but the process is not
    killed, matching typical build-tool behaviour).
    """

    def __init__(
        self,
        callback: Optional[OutputCallback],
        limit: Optional[int],
    ) -> None:
        self._callback = callback
        self._limit = limit
        self._lock = threading.Lock()
        self.total = 0
        self.truncated = False

    def write(self, stream: str, chunk: bytes) -> None:
        with self._lock:
            if self._limit is not None:
                remaining = self._limit - self.total
                if remaining <= 0:
                    self.truncated = True
                    return
                if len(chunk) > remaining:
                    chunk = chunk[:remaining]
                    self.truncated = True
            self.total += len(chunk)
        if self._callback is not None:
            self._callback(stream, chunk)


def _reader(pipe, stream: str, sink: _OutputSink) -> None:
    try:
        while True:
            chunk = pipe.read(_READ_CHUNK)
            if not chunk:
                break
            sink.write(stream, chunk)
    except (ValueError, OSError):
        # Pipe closed during shutdown; treat as end of stream.
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _popen_kwargs(spec: CommandSpec) -> dict:
    kwargs: dict = {}
    if _IS_WINDOWS:
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _signal_group(proc: "subprocess.Popen", sig: int, *, force: bool) -> None:
    """Best-effort delivery of a signal to the process and its descendants."""
    if proc.poll() is not None:
        return
    if _IS_WINDOWS:  # pragma: no cover - exercised on Windows only
        if force:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                )
                return
            except OSError:
                pass
        proc.terminate()
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate() if not force else proc.kill()
        except OSError:
            pass


def _terminate(proc: "subprocess.Popen", grace: float) -> None:
    """Ask politely, then force if needed. Never hangs indefinitely."""
    import signal

    _signal_group(proc, signal.SIGTERM, force=False)
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    _signal_group(proc, signal.SIGKILL, force=True)
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:  # pragma: no cover - extreme fallback
        pass


def run_command(
    spec: CommandSpec,
    *,
    on_output: Optional[OutputCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    grace_seconds: float = _GRACE_PERIOD_SECONDS,
) -> ProcessResult:
    """Run ``spec`` to completion and return a :class:`ProcessResult`.

    Raises:
        ProcessStartError: if the process cannot be started at all.
    """
    sink = _OutputSink(on_output, spec.max_output_bytes)

    if spec.shell:
        if len(spec.argv) != 1:
            raise ProcessStartError("shell execution requires a single command string")
        popen_argv: Union[str, Sequence[str]] = spec.argv[0]
    else:
        popen_argv = list(spec.argv)

    try:
        proc = subprocess.Popen(  # noqa: S603 - argv, no shell by default
            popen_argv,
            cwd=str(spec.cwd),
            env=dict(spec.env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            shell=spec.shell,
            **_popen_kwargs(spec),
        )
    except FileNotFoundError as exc:
        raise ProcessStartError(
            "executable not found: %s" % (spec.argv[0] if spec.argv else "")
        ) from exc
    except PermissionError as exc:
        raise ProcessStartError(
            "permission denied executing: %s" % (spec.argv[0] if spec.argv else "")
        ) from exc
    except OSError as exc:
        raise ProcessStartError("failed to start process: %s" % exc) from exc

    assert proc.stdout is not None and proc.stderr is not None
    stdout_thread = threading.Thread(
        target=_reader, args=(proc.stdout, "stdout", sink), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_reader, args=(proc.stderr, "stderr", sink), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()

    start = time.monotonic()
    deadline = (
        start + spec.timeout_seconds if spec.timeout_seconds is not None else None
    )
    timed_out = False
    cancelled = False

    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            _terminate(proc, grace_seconds)
            break
        if deadline is not None and time.monotonic() >= deadline:
            timed_out = True
            _terminate(proc, grace_seconds)
            break
        time.sleep(_POLL_INTERVAL)

    exit_code = proc.wait()
    stdout_thread.join(timeout=grace_seconds)
    stderr_thread.join(timeout=grace_seconds)
    duration = time.monotonic() - start

    return ProcessResult(
        exit_code=exit_code,
        timed_out=timed_out,
        cancelled=cancelled,
        duration_seconds=duration,
        output_bytes=sink.total,
        output_truncated=sink.truncated,
    )
