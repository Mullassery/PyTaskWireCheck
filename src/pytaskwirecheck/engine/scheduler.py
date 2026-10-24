"""The DAG scheduler.

The scheduler owns task-state transitions. It selects ready tasks, respects the
worker limit, applies failure policy, and drives the executor. It never renders
output or writes cache artifacts directly; it delegates to the executor and
publishes events.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Set

from pytaskwirecheck.config.schema import ExecutionConfig
from pytaskwirecheck.diagnostics.errors import ExecutionError
from pytaskwirecheck.engine.cancellation import CancellationToken
from pytaskwirecheck.engine.events import (
    EventBus,
    RunFinished,
    RunStarted,
    TaskStateChanged,
)
from pytaskwirecheck.engine.executor import TaskExecutor, TaskOutcome
from pytaskwirecheck.engine.state import TaskRecord, TaskStatus
from pytaskwirecheck.graph.model import TaskGraph

#: Version of the ``run --json`` summary contract. Bump on breaking changes.
RUN_SUMMARY_SCHEMA_VERSION = 1


@dataclass
class RunResult:
    """The aggregate outcome of a scheduler run."""

    run_id: str
    records: Dict[str, TaskRecord]
    duration_seconds: float
    cancelled: bool = False

    @property
    def succeeded(self) -> bool:
        for record in self.records.values():
            if not record.status.is_success:
                return False
        return True

    @property
    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for record in self.records.values():
            key = record.status.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def summary(self) -> dict:
        tasks = {}
        for task_id, record in self.records.items():
            tasks[task_id] = {
                "status": record.status.value,
                "exit_code": record.exit_code,
                "attempts": record.attempt,
                "duration_seconds": round(record.duration_seconds, 4),
                "cache_hit": record.cache_hit,
                "message": record.message,
            }
        return {
            "schema_version": RUN_SUMMARY_SCHEMA_VERSION,
            "run_id": self.run_id,
            "succeeded": self.succeeded,
            "cancelled": self.cancelled,
            "duration_seconds": round(self.duration_seconds, 4),
            "counts": self.counts,
            "tasks": tasks,
        }


class Scheduler:
    """Executes a selected subgraph of tasks with bounded concurrency."""

    def __init__(
        self,
        *,
        graph: TaskGraph,
        execution: ExecutionConfig,
        executor: TaskExecutor,
        events: EventBus,
        cancel_token: CancellationToken,
        use_cache: bool = True,
    ) -> None:
        self._graph = graph
        self._execution = execution
        self._executor = executor
        self._events = events
        self._cancel = cancel_token
        self._use_cache = use_cache
        self._lock = threading.Lock()

    def run(self, selected: Set[str], *, run_id: Optional[str] = None) -> RunResult:
        """Execute the selected tasks and return a :class:`RunResult`."""
        if not selected:
            raise ExecutionError("no tasks selected for execution")

        known = set(self._graph.nodes.keys())
        selected = {t for t in selected if t in known}
        order_index = {
            task_id: index for index, task_id in enumerate(self._graph.nodes.keys())
        }

        records: Dict[str, TaskRecord] = {
            task_id: TaskRecord(
                task_id=task_id,
                max_attempts=max(1, self._graph.get(task_id).config.retry.max_attempts),
            )
            for task_id in selected
        }

        remaining: Dict[str, int] = {}
        for task_id in selected:
            deps = [d for d in self._graph.dependencies(task_id) if d in selected]
            remaining[task_id] = len(deps)

        ready: List[str] = sorted(
            (t for t in selected if remaining[t] == 0),
            key=order_index.__getitem__,
        )

        run_id = run_id or uuid.uuid4().hex[:12]
        started = time.monotonic()
        self._events.emit(
            RunStarted(
                run_id=run_id, tasks=tuple(sorted(selected)), total_tasks=len(selected)
            )
        )

        stop_scheduling = False
        future_to_task: Dict[Future, str] = {}
        running: Dict[str, Future] = {}

        with ThreadPoolExecutor(
            max_workers=self._execution.max_workers,
            thread_name_prefix="pytaskwirecheck-worker",
        ) as pool:
            while ready or running:
                if self._cancel.is_cancelled:
                    stop_scheduling = True

                while (
                    ready
                    and not stop_scheduling
                    and len(running) < self._execution.max_workers
                ):
                    task_id = ready.pop(0)
                    record = records[task_id]
                    if record.status is not TaskStatus.PENDING:
                        continue
                    dependency_keys = {
                        dep: records[dep].cache_key
                        for dep in self._graph.dependencies(task_id)
                        if dep in selected
                    }
                    record.transition(TaskStatus.READY)
                    record.transition(TaskStatus.RUNNING)
                    record.started_at = time.monotonic()
                    self._events.emit(
                        TaskStateChanged(task_id=task_id, status=TaskStatus.RUNNING)
                    )
                    future = pool.submit(self._execute_task, task_id, dependency_keys)
                    future_to_task[future] = task_id
                    running[task_id] = future

                if not running:
                    break

                done, _ = wait(list(running.values()), return_when=FIRST_COMPLETED)
                for future in done:
                    task_id = future_to_task.pop(future)
                    running.pop(task_id, None)
                    try:
                        outcome = future.result()
                    except Exception as exc:  # pragma: no cover - defensive
                        outcome = TaskOutcome(
                            task_id=task_id,
                            status=TaskStatus.FAILED,
                            message="internal executor error: %s" % exc,
                        )
                    self._apply_outcome(
                        outcome,
                        records,
                        remaining,
                        ready,
                        order_index,
                        selected,
                    )
                    if outcome.status.is_failure:
                        if self._execution.fail_fast:
                            stop_scheduling = True
                            if not self._cancel.is_cancelled:
                                self._cancel.cancel(
                                    "fail-fast: task '%s' %s"
                                    % (task_id, outcome.status.value)
                                )

        # Any task not started (e.g. fail-fast) becomes cancelled.
        for task_id, record in records.items():
            if not record.status.is_terminal:
                record.transition(
                    TaskStatus.CANCELLED,
                    message="not started",
                )
                self._events.emit(
                    TaskStateChanged(
                        task_id=task_id,
                        status=TaskStatus.CANCELLED,
                        message="not started",
                    )
                )

        duration = time.monotonic() - started
        result = RunResult(
            run_id=run_id,
            records=records,
            duration_seconds=duration,
            cancelled=self._cancel.is_cancelled,
        )
        self._events.emit(
            RunFinished(
                run_id=run_id,
                succeeded=result.succeeded,
                summary=result.summary(),
            )
        )
        return result

    def _execute_task(
        self, task_id: str, dependency_keys: Mapping[str, Optional[str]]
    ) -> TaskOutcome:
        task = self._graph.get(task_id).config
        return self._executor.execute(task, dependency_keys, use_cache=self._use_cache)

    def _apply_outcome(
        self,
        outcome: TaskOutcome,
        records: Dict[str, TaskRecord],
        remaining: Dict[str, int],
        ready: List[str],
        order_index: Mapping[str, int],
        selected: Set[str],
    ) -> None:
        task_id = outcome.task_id
        record = records[task_id]
        record.attempt = outcome.attempts
        record.exit_code = outcome.exit_code
        record.duration_seconds = outcome.duration_seconds
        record.cache_hit = outcome.cache_hit
        record.cache_key = outcome.cache_key
        record.output_bytes = outcome.output_bytes
        record.finished_at = time.monotonic()
        record.transition(outcome.status, message=outcome.message)
        self._events.emit(
            TaskStateChanged(
                task_id=task_id,
                status=outcome.status,
                message=outcome.message,
            )
        )

        if outcome.status.is_success:
            newly_ready: List[str] = []
            for dependent in self._graph.dependents(task_id):
                if dependent not in selected:
                    continue
                if remaining.get(dependent, 0) > 0:
                    remaining[dependent] -= 1
                if (
                    remaining.get(dependent) == 0
                    and records[dependent].status is TaskStatus.PENDING
                ):
                    newly_ready.append(dependent)
            if newly_ready:
                ready.extend(newly_ready)
                ready.sort(key=order_index.__getitem__)
            return

        # Failure (including cancellation/timeout): block transitive dependents.
        self._block_dependents(task_id, records, selected)

    def _block_dependents(
        self,
        task_id: str,
        records: Dict[str, TaskRecord],
        selected: Set[str],
    ) -> None:
        stack = [task_id]
        while stack:
            current = stack.pop()
            for dependent in self._graph.dependents(current):
                if dependent not in selected:
                    continue
                record = records[dependent]
                if record.status in (TaskStatus.PENDING, TaskStatus.READY):
                    record.transition(
                        TaskStatus.BLOCKED,
                        message="upstream task failed",
                    )
                    self._events.emit(
                        TaskStateChanged(
                            task_id=dependent,
                            status=TaskStatus.BLOCKED,
                            message="upstream task failed",
                        )
                    )
                    stack.append(dependent)
