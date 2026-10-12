"""Per-task execution: environment, timeout, retries, and cache integration.

The executor runs exactly one task to a terminal state. It is driven by the
scheduler one call per task; it does not know about other tasks except through
the dependency cache keys passed in by the scheduler.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Protocol

from pytaskwirecheck.config.schema import TaskConfig
from pytaskwirecheck.diagnostics.errors import ProcessStartError
from pytaskwirecheck.engine.cancellation import CancellationToken
from pytaskwirecheck.engine.events import (
    EventBus,
    TaskAttemptFinished,
    TaskAttemptStarted,
    TaskOutput,
)
from pytaskwirecheck.engine.state import TaskStatus
from pytaskwirecheck.processes.runner import CommandSpec, ProcessResult, run_command


@dataclass
class TaskOutcome:
    """The terminal outcome of executing a single task."""

    task_id: str
    status: TaskStatus
    exit_code: Optional[int] = None
    attempts: int = 0
    duration_seconds: float = 0.0
    message: str = ""
    cache_hit: bool = False
    cache_key: Optional[str] = None
    output_bytes: int = 0


class CacheBackend(Protocol):
    """Structural interface for the content-addressed cache (Phase 3)."""

    def try_restore(
        self, task: TaskConfig, dependency_keys: Mapping[str, Optional[str]]
    ) -> Optional[str]:
        """Return a cache key if a valid entry was restored, else ``None``."""

    def store(
        self, task: TaskConfig, dependency_keys: Mapping[str, Optional[str]]
    ) -> Optional[str]:
        """Commit a successful result; return the cache key (or ``None``)."""


def build_environment(
    task: TaskConfig, base_env: Mapping[str, str]
) -> Mapping[str, str]:
    """Compose the subprocess environment for ``task``.

    Secret values are never logged; only the set of overridden names is ever
    exposed to presentation.
    """
    env = dict(base_env) if task.inherit_env else {}
    env.update(task.env)
    return env


def resolve_cwd(root: Path, task: TaskConfig) -> Path:
    if task.cwd:
        return (root / task.cwd).resolve()
    return root


class TaskExecutor:
    """Runs a single task with retries and optional cache integration."""

    def __init__(
        self,
        *,
        root: Path,
        default_timeout: Optional[float],
        events: EventBus,
        cancel_token: CancellationToken,
        base_env: Optional[Mapping[str, str]] = None,
        cache: Optional[CacheBackend] = None,
        grace_seconds: float = 5.0,
    ) -> None:
        self._root = root
        self._default_timeout = default_timeout
        self._events = events
        self._cancel = cancel_token
        self._base_env = base_env if base_env is not None else os.environ
        self._cache = cache
        self._grace = grace_seconds

    def effective_timeout(self, task: TaskConfig) -> Optional[float]:
        if task.timeout_seconds is not None:
            return task.timeout_seconds
        return self._default_timeout

    def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep up to ``seconds``; return ``False`` if cancellation occurred."""
        remaining = seconds
        step = 0.1
        while remaining > 0:
            if self._cancel.is_cancelled:
                return False
            time.sleep(min(step, remaining))
            remaining -= step
        return not self._cancel.is_cancelled

    def execute(
        self,
        task: TaskConfig,
        dependency_keys: Optional[Mapping[str, Optional[str]]] = None,
        *,
        use_cache: bool = True,
    ) -> TaskOutcome:
        """Execute ``task`` and return its terminal :class:`TaskOutcome`."""
        dependency_keys = dependency_keys or {}

        if self._cancel.is_cancelled:
            return TaskOutcome(
                task_id=task.id,
                status=TaskStatus.CANCELLED,
                message=self._cancel.reason or "cancelled before start",
            )

        if use_cache and self._cache is not None and task.cache_eligible:
            key = self._cache.try_restore(task, dependency_keys)
            if key is not None:
                return TaskOutcome(
                    task_id=task.id,
                    status=TaskStatus.CACHED,
                    cache_hit=True,
                    cache_key=key,
                    message="restored from cache",
                )

        spec = CommandSpec(
            argv=task.command,
            cwd=resolve_cwd(self._root, task),
            env=build_environment(task, self._base_env),
            shell=task.shell,
            timeout_seconds=self.effective_timeout(task),
            max_output_bytes=task.resources.max_output_bytes,
        )

        max_attempts = max(1, task.retry.max_attempts)
        attempt = 0
        total_duration = 0.0
        last_exit: Optional[int] = None

        while attempt < max_attempts:
            if self._cancel.is_cancelled:
                return TaskOutcome(
                    task_id=task.id,
                    status=TaskStatus.CANCELLED,
                    attempts=attempt,
                    duration_seconds=total_duration,
                    exit_code=last_exit,
                    message=self._cancel.reason or "cancelled",
                )
            attempt += 1
            self._events.emit(
                TaskAttemptStarted(
                    task_id=task.id, attempt=attempt, max_attempts=max_attempts
                )
            )

            def _on_output(stream: str, chunk: bytes, _id: str = task.id) -> None:
                self._events.emit(TaskOutput(task_id=_id, stream=stream, data=chunk))

            started = time.monotonic()
            try:
                result = run_command(
                    spec,
                    on_output=_on_output,
                    cancel_event=self._cancel.event,
                    grace_seconds=self._grace,
                )
            except ProcessStartError as exc:
                total_duration += time.monotonic() - started
                self._events.emit(
                    TaskAttemptFinished(
                        task_id=task.id,
                        attempt=attempt,
                        status=TaskStatus.FAILED,
                        exit_code=None,
                        duration_seconds=total_duration,
                    )
                )
                return TaskOutcome(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    attempts=attempt,
                    duration_seconds=total_duration,
                    message=str(exc),
                )

            duration = result.duration_seconds
            total_duration += duration
            last_exit = result.exit_code
            status = self._classify(result)
            self._events.emit(
                TaskAttemptFinished(
                    task_id=task.id,
                    attempt=attempt,
                    status=status,
                    exit_code=result.exit_code,
                    duration_seconds=duration,
                )
            )

            if status is TaskStatus.SUCCEEDED:
                cache_key = None
                if use_cache and self._cache is not None and task.cache_eligible:
                    cache_key = self._cache.store(task, dependency_keys)
                return TaskOutcome(
                    task_id=task.id,
                    status=TaskStatus.SUCCEEDED,
                    exit_code=result.exit_code,
                    attempts=attempt,
                    duration_seconds=total_duration,
                    cache_key=cache_key,
                    output_bytes=result.output_bytes,
                )

            if status is TaskStatus.CANCELLED:
                return TaskOutcome(
                    task_id=task.id,
                    status=TaskStatus.CANCELLED,
                    exit_code=result.exit_code,
                    attempts=attempt,
                    duration_seconds=total_duration,
                    message=self._cancel.reason or "cancelled",
                )

            # Decide whether to retry.
            retryable = self._is_retryable(task, result, status)
            if not retryable or attempt >= max_attempts:
                return TaskOutcome(
                    task_id=task.id,
                    status=status,
                    exit_code=result.exit_code,
                    attempts=attempt,
                    duration_seconds=total_duration,
                    output_bytes=result.output_bytes,
                    message=self._failure_message(result, status),
                )
            delay = task.retry.delay_for_attempt(attempt + 1)
            if delay > 0 and not self._interruptible_sleep(delay):
                return TaskOutcome(
                    task_id=task.id,
                    status=TaskStatus.CANCELLED,
                    attempts=attempt,
                    duration_seconds=total_duration,
                    message=self._cancel.reason or "cancelled during retry delay",
                )

        # Unreachable: loop always returns. Defensive fallback.
        return TaskOutcome(
            task_id=task.id,
            status=TaskStatus.FAILED,
            exit_code=last_exit,
            attempts=attempt,
            duration_seconds=total_duration,
            message="exhausted attempts",
        )

    @staticmethod
    def _classify(result: ProcessResult) -> TaskStatus:
        if result.cancelled:
            return TaskStatus.CANCELLED
        if result.timed_out:
            return TaskStatus.TIMED_OUT
        if result.exit_code == 0:
            return TaskStatus.SUCCEEDED
        return TaskStatus.FAILED

    def _is_retryable(
        self, task: TaskConfig, result: ProcessResult, status: TaskStatus
    ) -> bool:
        if not task.retry.enabled:
            return False
        if status is TaskStatus.TIMED_OUT:
            return True
        if status is TaskStatus.FAILED and result.exit_code is not None:
            return task.retry.should_retry_exit_code(result.exit_code)
        return False

    @staticmethod
    def _failure_message(result: ProcessResult, status: TaskStatus) -> str:
        if status is TaskStatus.TIMED_OUT:
            return "timed out"
        if result.exit_code is not None:
            return "exited with code %d" % result.exit_code
        return "failed"
