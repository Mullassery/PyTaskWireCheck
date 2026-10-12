"""High-level Python API for embedding PyTaskWireCheck.

The command-line interface is a thin shell over this module. Library users can
load a workflow, inspect its plan, and execute it in-process::

    from pytaskwirecheck import Workflow

    workflow = Workflow.from_file("pytaskwirecheck.toml")
    result = workflow.run()
    if not result.succeeded:
        raise SystemExit(1)

Everything here is local-only. Importing this module never executes tasks,
touches the network, or reads configuration implicitly; work begins only when
:meth:`Workflow.run` is called.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Set, Union

from pytaskwirecheck.cache.policy import build_store
from pytaskwirecheck.config.loader import find_config, load_config, parse_toml
from pytaskwirecheck.config.schema import ExecutionConfig, WorkflowConfig
from pytaskwirecheck.config.validation import build_workflow
from pytaskwirecheck.diagnostics.errors import ConfigError, HistoryError
from pytaskwirecheck.engine.cancellation import CancellationToken
from pytaskwirecheck.engine.events import EventBus
from pytaskwirecheck.engine.executor import TaskExecutor
from pytaskwirecheck.engine.scheduler import RunResult, Scheduler
from pytaskwirecheck.graph.builder import build_graph
from pytaskwirecheck.graph.model import TaskGraph
from pytaskwirecheck.graph.planner import ExecutionPlan, build_plan, resolve_targets
from pytaskwirecheck.graph.validator import validate_graph
from pytaskwirecheck.history.store import HistoryStore
from pytaskwirecheck.notifications.base import RunNotification
from pytaskwirecheck.notifications.webhook import WebhookNotifier

_log = logging.getLogger("pytaskwirecheck")

EventCallback = Callable[[Any], None]


class Workflow:
    """A loaded, validated workflow that can be planned and executed."""

    def __init__(self, config: WorkflowConfig) -> None:
        self._config = config
        self._graph: Optional[TaskGraph] = None

    # -- construction ------------------------------------------------------

    @classmethod
    def from_file(
        cls,
        path: Optional[Union[str, Path]] = None,
        *,
        root: Optional[Union[str, Path]] = None,
    ) -> "Workflow":
        """Load a workflow from ``path`` or the nearest ``pytaskwirecheck.toml``."""
        if path is None:
            found = find_config(Path.cwd())
            if found is None:
                raise ConfigError(
                    "no pytaskwirecheck.toml found in %s or any parent directory"
                    % Path.cwd()
                )
            config_path = found
        else:
            config_path = Path(path).resolve()
        root_override = str(root) if root is not None else None
        return cls(load_config(config_path, root_override=root_override))

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        root: Optional[Union[str, Path]] = None,
        name: str = "pytaskwirecheck.toml",
    ) -> "Workflow":
        """Parse a workflow from an in-memory TOML document."""
        base = Path(root).resolve() if root is not None else Path.cwd()
        raw = parse_toml(text, location=name)
        config = build_workflow(raw, base, base / name)
        return cls(config)

    # -- inspection --------------------------------------------------------

    @property
    def config(self) -> WorkflowConfig:
        """The validated workflow configuration."""
        return self._config

    @property
    def graph(self) -> TaskGraph:
        """The validated task graph, built once and cached."""
        if self._graph is None:
            graph = build_graph(self._config)
            validate_graph(graph)
            self._graph = graph
        return self._graph

    def validate(self) -> ExecutionPlan:
        """Validate the workflow and return the full execution plan."""
        return build_plan(self.graph)

    def plan(self, targets: Optional[Sequence[str]] = None) -> ExecutionPlan:
        """Return the execution plan for ``targets`` (or everything)."""
        graph = self.graph
        subset: Optional[Set[str]] = None
        if targets:
            subset = resolve_targets(graph, list(targets))
        return build_plan(graph, subset)

    # -- execution ---------------------------------------------------------

    def run(
        self,
        targets: Optional[Sequence[str]] = None,
        *,
        use_cache: bool = True,
        max_workers: Optional[int] = None,
        fail_fast: Optional[bool] = None,
        on_event: Optional[EventCallback] = None,
        cancel_token: Optional[CancellationToken] = None,
        record_history: bool = True,
        notify: bool = True,
    ) -> RunResult:
        """Execute the workflow and return the aggregate :class:`RunResult`.

        ``on_event`` receives every engine event, enabling custom progress
        reporting. ``cancel_token`` allows cooperative cancellation from
        another thread. History and notifications are best-effort and never
        alter the returned result.
        """
        graph = self.graph
        selected: Set[str] = (
            resolve_targets(graph, list(targets)) if targets else set(graph.nodes)
        )
        execution = self._resolve_execution(max_workers, fail_fast)
        run_id = uuid.uuid4().hex[:12]

        events = EventBus()
        if on_event is not None:
            events.subscribe(on_event)
        token = cancel_token if cancel_token is not None else CancellationToken()

        cache_enabled = self._config.cache.enabled and use_cache
        store = build_store(self._config) if cache_enabled else None

        executor = TaskExecutor(
            root=self._config.project.root,
            default_timeout=execution.default_timeout_seconds,
            events=events,
            cancel_token=token,
            cache=store,
        )
        scheduler = Scheduler(
            graph=graph,
            execution=execution,
            executor=executor,
            events=events,
            cancel_token=token,
            use_cache=cache_enabled,
        )
        result = scheduler.run(selected, run_id=run_id)

        if record_history:
            self._record_history(result)
        if notify:
            self._notify(result)
        return result

    # -- helpers -----------------------------------------------------------

    def _resolve_execution(
        self, max_workers: Optional[int], fail_fast: Optional[bool]
    ) -> ExecutionConfig:
        execution = self._config.execution
        if max_workers is None and fail_fast is None:
            return execution
        if max_workers is not None and max_workers < 1:
            raise ConfigError("max_workers must be >= 1")
        return ExecutionConfig(
            max_workers=(
                max_workers if max_workers is not None else execution.max_workers
            ),
            default_timeout_seconds=execution.default_timeout_seconds,
            fail_fast=(fail_fast if fail_fast is not None else execution.fail_fast),
        )

    def _record_history(self, result: RunResult) -> None:
        if not self._config.history.enabled:
            return
        store = HistoryStore(
            self._config.project.root, max_runs=self._config.history.max_runs
        )
        try:
            store.record_run(
                result,
                project=self._config.project.name,
                config_version=self._config.project.version,
            )
        except HistoryError as exc:
            _log.warning("could not record history: %s", exc)
        finally:
            store.close()

    def _notify(self, result: RunResult) -> None:
        settings = self._config.notifications
        if not settings.enabled:
            return
        event = "success" if result.succeeded else "failure"
        notifier = WebhookNotifier(
            settings.url,
            timeout_seconds=settings.timeout_seconds,
            max_attempts=settings.max_attempts,
            events=settings.on,
        )
        if not notifier.wants(event):
            return
        notification = RunNotification(
            event=event,
            run_id=result.run_id,
            project=self._config.project.name,
            succeeded=result.succeeded,
            cancelled=result.cancelled,
            duration_seconds=result.duration_seconds,
            counts=result.counts,
            failed_tasks=self._failed_tasks(result),
        )
        try:
            delivered = notifier.send(notification)
        except Exception as exc:  # defensive: never break the run
            _log.warning("notification failed: %s", type(exc).__name__)
            return
        if not delivered:
            _log.warning("notification was not delivered")

    @staticmethod
    def _failed_tasks(result: RunResult) -> List[dict]:
        failed = []
        for task_id, record in sorted(result.records.items()):
            if record.status.is_failure:
                failed.append(
                    {
                        "task": task_id,
                        "status": record.status.value,
                        "exit_code": record.exit_code,
                    }
                )
        return failed


# ---------------------------------------------------------------------------
# Functional conveniences
# ---------------------------------------------------------------------------


def load_workflow(
    path: Optional[Union[str, Path]] = None,
    *,
    root: Optional[Union[str, Path]] = None,
) -> Workflow:
    """Load a :class:`Workflow` from ``path`` or the nearest config file."""
    return Workflow.from_file(path, root=root)


def validate(
    path: Optional[Union[str, Path]] = None,
    *,
    root: Optional[Union[str, Path]] = None,
) -> ExecutionPlan:
    """Validate a workflow and return its full :class:`ExecutionPlan`."""
    return load_workflow(path, root=root).validate()


def plan(
    targets: Optional[Sequence[str]] = None,
    *,
    path: Optional[Union[str, Path]] = None,
    root: Optional[Union[str, Path]] = None,
) -> ExecutionPlan:
    """Return the plan for ``targets`` without executing anything."""
    return load_workflow(path, root=root).plan(targets)


def run(
    targets: Optional[Sequence[str]] = None,
    *,
    path: Optional[Union[str, Path]] = None,
    root: Optional[Union[str, Path]] = None,
    use_cache: bool = True,
    max_workers: Optional[int] = None,
    fail_fast: Optional[bool] = None,
    on_event: Optional[EventCallback] = None,
    record_history: bool = True,
    notify: bool = True,
) -> RunResult:
    """Load and execute a workflow in one call."""
    workflow = load_workflow(path, root=root)
    return workflow.run(
        targets,
        use_cache=use_cache,
        max_workers=max_workers,
        fail_fast=fail_fast,
        on_event=on_event,
        record_history=record_history,
        notify=notify,
    )
