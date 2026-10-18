"""PyTaskWireCheck command-line interface.

Commands are intentionally thin: they load/validate configuration, build and
validate the graph, and delegate execution to the engine. All user-facing
errors are reported concisely with a stable exit code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import List, Optional, Sequence, TextIO

from pytaskwirecheck import __version__
from pytaskwirecheck.cache.policy import build_store, decide
from pytaskwirecheck.config.loader import find_config, load_config
from pytaskwirecheck.config.schema import WorkflowConfig
from pytaskwirecheck.diagnostics.errors import (
    ConfigError,
    GraphError,
    HistoryError,
    PyTaskWireCheckError,
)
from pytaskwirecheck.engine.cancellation import CancellationToken
from pytaskwirecheck.engine.events import EventBus
from pytaskwirecheck.engine.executor import TaskExecutor
from pytaskwirecheck.engine.scheduler import RunResult, Scheduler
from pytaskwirecheck.graph.builder import build_graph
from pytaskwirecheck.graph.model import TaskGraph
from pytaskwirecheck.graph.planner import build_plan, resolve_targets
from pytaskwirecheck.graph.validator import validate_graph
from pytaskwirecheck.history.store import HistoryStore
from pytaskwirecheck.logging.artifacts import ArtifactWriter
from pytaskwirecheck.logging.structured import StructuredLogger
from pytaskwirecheck.notifications.base import RunNotification
from pytaskwirecheck.notifications.webhook import WebhookNotifier
from pytaskwirecheck.processes.signals import install_cancel_handlers
from pytaskwirecheck.tui.app import LiveDashboard
from pytaskwirecheck.tui.renderer import PlainReporter

EXIT_OK = 0
EXIT_TASK_FAILURE = 1
EXIT_USAGE = 2
EXIT_GRAPH = 3
EXIT_INTERRUPTED = 130

_STARTER_CONFIG = """\
[project]
name = "example-workflow"
version = 1

[execution]
max_workers = 4
default_timeout_seconds = 900
fail_fast = false

[tasks.greet]
command = ["python", "-c", "print('hello from PyTaskWireCheck')"]
description = "A trivial, dependency-free first task"

[tasks.describe]
command = ["python", "-c", "print('workspace ready')"]
depends_on = ["greet"]
description = "Runs after greet"
"""


def _err(stream: TextIO, message: str) -> None:
    try:
        stream.write("pytaskwirecheck: error: %s\n" % message)
        stream.flush()
    except (BrokenPipeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pytaskwirecheck",
        description="Local-first, dependency-aware task orchestration.",
    )
    parser.add_argument(
        "--version", action="version", version="pytaskwirecheck %s" % __version__
    )
    parser.add_argument(
        "-C",
        "--root",
        dest="root",
        default=None,
        help="project root (defaults to the config file's directory)",
    )
    parser.add_argument(
        "--config",
        dest="config",
        default=None,
        help="path to pytaskwirecheck.toml (defaults to nearest file)",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="disable ANSI colour output"
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # init
    p_init = sub.add_parser("init", help="create a starter configuration")
    p_init.add_argument(
        "--path", default=".", help="directory to create pytaskwirecheck.toml in"
    )
    p_init.add_argument(
        "--force", action="store_true", help="overwrite an existing file"
    )
    p_init.set_defaults(func=cmd_init)

    # validate
    p_val = sub.add_parser("validate", help="validate configuration and graph")
    p_val.add_argument(
        "--json", action="store_true", help="emit machine-readable output"
    )
    p_val.set_defaults(func=cmd_validate)

    # graph
    p_graph = sub.add_parser("graph", help="display the task DAG")
    p_graph.add_argument(
        "--format",
        choices=["text", "dot", "json"],
        default="text",
        help="output format",
    )
    p_graph.set_defaults(func=cmd_graph)

    # plan
    p_plan = sub.add_parser("plan", help="show the execution plan")
    p_plan.add_argument(
        "tasks", nargs="*", help="restrict to these tasks and their dependencies"
    )
    p_plan.add_argument("--json", action="store_true", help="emit JSON")
    p_plan.set_defaults(func=cmd_plan)

    # run
    p_run = sub.add_parser("run", help="execute tasks")
    p_run.add_argument("tasks", nargs="*", help="tasks to run (defaults to all)")
    p_run.add_argument(
        "--no-cache", action="store_true", help="disable cache reads and writes"
    )
    p_run.add_argument(
        "--max-workers", type=int, default=None, help="override worker count"
    )
    p_run.add_argument(
        "--fail-fast",
        dest="fail_fast",
        action="store_true",
        default=None,
        help="stop launching new tasks after the first failure",
    )
    p_run.add_argument(
        "--no-fail-fast",
        dest="fail_fast",
        action="store_false",
        help="allow unrelated branches to continue after a failure",
    )
    p_run.add_argument("--json", action="store_true", help="emit a JSON run summary")
    p_run.add_argument(
        "-q", "--quiet", action="store_true", help="suppress progress output"
    )
    p_run.add_argument(
        "--no-output",
        action="store_true",
        help="do not stream task output to the console",
    )
    p_run.add_argument(
        "--tui",
        action="store_true",
        help="show a live dashboard when attached to a TTY",
    )
    p_run.set_defaults(func=cmd_run)

    # cache
    p_cache = sub.add_parser("cache", help="inspect or clean the cache")
    cache_sub = p_cache.add_subparsers(dest="cache_command", metavar="ACTION")
    cache_sub.required = True
    p_cache_status = cache_sub.add_parser("status", help="show cache statistics")
    p_cache_status.add_argument("--json", action="store_true")
    p_cache_status.set_defaults(func=cmd_cache_status)
    p_cache_clean = cache_sub.add_parser("clean", help="remove cached data")
    p_cache_clean.add_argument(
        "--force", action="store_true", help="do not prompt for confirmation"
    )
    p_cache_clean.add_argument("--json", action="store_true")
    p_cache_clean.set_defaults(func=cmd_cache_clean)
    p_cache_evict = cache_sub.add_parser(
        "evict", help="evict least-recently-used entries to honor the size/count bounds"
    )
    p_cache_evict.add_argument("--json", action="store_true")
    p_cache_evict.set_defaults(func=cmd_cache_evict)

    # explain
    p_explain = sub.add_parser(
        "explain", help="explain scheduling and cache status for a task"
    )
    p_explain.add_argument("task", help="task identifier")
    p_explain.add_argument("--json", action="store_true")
    p_explain.set_defaults(func=cmd_explain)

    # history
    p_history = sub.add_parser("history", help="show recent execution summaries")
    p_history.add_argument(
        "--limit", type=int, default=20, help="number of runs to show"
    )
    p_history.add_argument("--json", action="store_true")
    p_history.set_defaults(func=cmd_history)

    return parser


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_config_path(args: argparse.Namespace) -> Path:
    if args.config:
        return Path(args.config).resolve()
    found = find_config(Path.cwd())
    if found is None:
        raise ConfigError(
            "no pytaskwirecheck.toml found in %s or any parent directory" % Path.cwd()
        )
    return found


def _load(args: argparse.Namespace) -> WorkflowConfig:
    config_path = _resolve_config_path(args)
    return load_config(config_path, root_override=args.root)


def _prepare_graph(
    config: WorkflowConfig,
) -> TaskGraph:
    graph = build_graph(config)
    validate_graph(graph)
    return graph


def _color_enabled(args: argparse.Namespace, stream: TextIO) -> bool:
    if getattr(args, "no_color", False):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(stream.isatty())
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    target_dir = Path(args.path).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    config_path = target_dir / "pytaskwirecheck.toml"
    if config_path.exists() and not args.force:
        _err(sys.stderr, "%s already exists (use --force)" % config_path)
        return EXIT_USAGE
    config_path.write_text(_STARTER_CONFIG, encoding="utf-8")
    print("Created %s" % config_path)
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    config = _load(args)
    graph = _prepare_graph(config)
    plan = build_plan(graph)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "project": config.project.name,
                    "config_version": config.project.version,
                    "task_count": len(config.tasks),
                    "tasks": sorted(config.tasks.keys()),
                    "levels": [list(level) for level in plan.levels],
                },
                indent=2,
            )
        )
    else:
        print(
            "configuration OK: %d task(s), %d level(s)"
            % (len(config.tasks), len(plan.levels))
        )
    return EXIT_OK


def _graph_text(graph: TaskGraph) -> str:
    lines: List[str] = []
    for node in graph:
        if node.depends_on:
            deps = ", ".join(node.depends_on)
            lines.append("%s -> %s" % (deps, node.id))
        else:
            lines.append("%s (no dependencies)" % node.id)
    return "\n".join(lines)


def _graph_dot(graph: TaskGraph, name: str) -> str:
    lines = ["digraph %s {" % name]
    for node in graph:
        lines.append('  "%s";' % node.id)
        for dep in node.depends_on:
            lines.append('  "%s" -> "%s";' % (dep, node.id))
    lines.append("}")
    return "\n".join(lines)


def cmd_graph(args: argparse.Namespace) -> int:
    config = _load(args)
    graph = _prepare_graph(config)
    if args.format == "dot":
        print(_graph_dot(graph, config.project.name.replace("-", "_")))
    elif args.format == "json":
        payload = {
            "tasks": {node.id: {"depends_on": list(node.depends_on)} for node in graph}
        }
        print(json.dumps(payload, indent=2))
    else:
        print(_graph_text(graph))
    return EXIT_OK


def cmd_plan(args: argparse.Namespace) -> int:
    config = _load(args)
    graph = _prepare_graph(config)
    selected = resolve_targets(graph, args.tasks)
    plan = build_plan(graph, selected)
    if args.json:
        payload = {
            "project": config.project.name,
            "order": list(plan.order),
            "levels": [list(level) for level in plan.levels],
            "max_parallelism": plan.max_parallelism,
            "tasks": [
                {
                    "id": t.id,
                    "dependencies": list(t.dependencies),
                    "level": t.level,
                    "cache_eligible": t.cache_eligible,
                }
                for t in plan.tasks
            ],
        }
        print(json.dumps(payload, indent=2))
        return EXIT_OK
    print(
        "Plan for %d task(s), max parallelism %d:"
        % (len(plan.order), plan.max_parallelism)
    )
    for index, level in enumerate(plan.levels):
        print("  level %d: %s" % (index, ", ".join(level)))
    print("Order: %s" % " -> ".join(plan.order))
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    config = _load(args)
    graph = _prepare_graph(config)
    try:
        selected = resolve_targets(graph, args.tasks)
    except GraphError as exc:
        _err(sys.stderr, str(exc))
        return EXIT_GRAPH

    execution = config.execution
    if args.max_workers is not None:
        if args.max_workers < 1:
            _err(sys.stderr, "--max-workers must be >= 1")
            return EXIT_USAGE
        execution = type(execution)(
            max_workers=args.max_workers,
            default_timeout_seconds=execution.default_timeout_seconds,
            fail_fast=execution.fail_fast,
        )
    if args.fail_fast is not None:
        execution = type(execution)(
            max_workers=execution.max_workers,
            default_timeout_seconds=execution.default_timeout_seconds,
            fail_fast=args.fail_fast,
        )

    run_id = uuid.uuid4().hex[:12]
    events = EventBus()
    cancel_token = CancellationToken()

    use_cache = config.cache.enabled and not args.no_cache
    cache_store = build_store(config) if config.cache.enabled else None

    artifacts = ArtifactWriter(config.project.root, run_id)
    structured = StructuredLogger(config.project.root, run_id)
    reporter = PlainReporter(
        sys.stdout,
        color=_color_enabled(args, sys.stdout),
        quiet=args.quiet or args.json,
        show_output=not args.no_output,
    )
    events.subscribe(artifacts.handle)
    events.subscribe(structured.handle)
    use_tui = args.tui and not args.json
    dashboard = None
    if use_tui:
        dashboard = LiveDashboard(sys.stdout, color=_color_enabled(args, sys.stdout))
        events.subscribe(dashboard.handle)
    elif not args.json:
        events.subscribe(reporter.handle)

    executor = TaskExecutor(
        root=config.project.root,
        default_timeout=execution.default_timeout_seconds,
        events=events,
        cancel_token=cancel_token,
        cache=cache_store,
    )
    scheduler = Scheduler(
        graph=graph,
        execution=execution,
        executor=executor,
        events=events,
        cancel_token=cancel_token,
        use_cache=use_cache,
    )

    result: Optional[RunResult] = None
    try:
        if dashboard is not None:
            dashboard.start()
        with install_cancel_handlers(cancel_token.cancel):
            result = scheduler.run(selected, run_id=run_id)
    except KeyboardInterrupt:  # pragma: no cover
        cancel_token.cancel("interrupted")
        return EXIT_INTERRUPTED
    finally:
        if dashboard is not None:
            dashboard.stop()
        artifacts.close()
        structured.close()

    assert result is not None

    _record_history(config, result)
    _send_notifications(config, result)

    if args.json:
        print(json.dumps(result.summary(), indent=2))
    else:
        log_path = artifacts.path_for(next(iter(sorted(selected))))
        if log_path is not None and not args.quiet:
            print("Logs: %s" % log_path.parent)

    if result.cancelled and not result.succeeded:
        return EXIT_INTERRUPTED
    return EXIT_OK if result.succeeded else EXIT_TASK_FAILURE


# ---------------------------------------------------------------------------
# Cache and explain commands
# ---------------------------------------------------------------------------


def cmd_cache_status(args: argparse.Namespace) -> int:
    config = _load(args)
    store = build_store(config)
    status = store.status()
    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print("Cache location: %s" % status["location"])
        print("Entries: %d" % status["entries"])
        print("Size: %.2f KiB" % (status["size_bytes"] / 1024.0))
        if status["corrupted"]:
            print("Corrupted entries: %d" % status["corrupted"])
    return EXIT_OK


def cmd_cache_clean(args: argparse.Namespace) -> int:
    config = _load(args)
    store = build_store(config)
    if not args.force:
        try:
            interactive = sys.stdin.isatty()
        except (ValueError, AttributeError):
            interactive = False
        if not interactive:
            _err(
                sys.stderr,
                "refusing to clean without --force in a non-interactive session",
            )
            return EXIT_USAGE
        answer = input("Remove all cached data under %s? [y/N] " % store.location)
        if answer.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return EXIT_OK
    result = store.clean()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Removed %.2f KiB" % (result["removed_bytes"] / 1024.0))
    return EXIT_OK


def cmd_cache_evict(args: argparse.Namespace) -> int:
    config = _load(args)
    store = build_store(config)
    result = store.evict()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        noun = "entry" if result["removed_entries"] == 1 else "entries"
        print(
            "Evicted %d %s (%.2f KiB)"
            % (result["removed_entries"], noun, result["removed_bytes"] / 1024.0)
        )
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    config = _load(args)
    graph = _prepare_graph(config)
    if args.task not in graph.nodes:
        _err(sys.stderr, "unknown task: %s" % args.task)
        return EXIT_GRAPH
    node = graph.get(args.task)
    task = node.config
    decision = decide(task, global_enabled=config.cache.enabled, cli_disabled=False)
    info: dict = {
        "task": task.id,
        "description": task.description,
        "command": list(task.command),
        "shell": task.shell,
        "depends_on": list(node.depends_on),
        "dependents": list(node.dependents),
        "inputs": list(task.inputs),
        "outputs": list(task.outputs),
        "timeout_seconds": task.timeout_seconds,
        "retry": {
            "max_attempts": task.retry.max_attempts,
            "delay_seconds": task.retry.delay_seconds,
            "backoff": task.retry.backoff,
        },
        "cache": {"use_cache": decision.use_cache, "reason": decision.reason},
    }
    if decision.use_cache:
        store = build_store(config)
        dependency_keys = {dep: None for dep in node.depends_on}
        detail: dict = store.explain(task, dependency_keys)
        detail["note"] = "dependency cache keys assumed absent; a real run may differ"
        info["cache_detail"] = detail
    if args.json:
        print(json.dumps(info, indent=2))
        return EXIT_OK

    print("Task: %s" % task.id)
    if task.description:
        print("  %s" % task.description)
    print("  command: %s" % " ".join(task.command))
    print("  depends on: %s" % (", ".join(node.depends_on) or "(none)"))
    print("  inputs: %s" % (", ".join(task.inputs) or "(none)"))
    print("  outputs: %s" % (", ".join(task.outputs) or "(none)"))
    print("  cache: %s (%s)" % (decision.use_cache, decision.reason))
    if decision.use_cache and "cache_detail" in info:
        cache_detail: dict = info["cache_detail"]
        print(
            "  cache key: %s"
            % cache_detail.get("key", cache_detail.get("reason", "n/a"))
        )
        print("  cache hit: %s" % cache_detail.get("hit", False))
    return EXIT_OK


# ---------------------------------------------------------------------------
# Persistence and notifications (best-effort, never change run outcome)
# ---------------------------------------------------------------------------


def _record_history(config: WorkflowConfig, result: RunResult) -> None:
    if not config.history.enabled:
        return
    store = HistoryStore(config.project.root, max_runs=config.history.max_runs)
    try:
        store.record_run(
            result,
            project=config.project.name,
            config_version=config.project.version,
        )
    except HistoryError as exc:
        # Persistence must never alter the run's exit code or success state.
        _err(sys.stderr, "warning: could not record history: %s" % exc)
    finally:
        store.close()


def _failed_tasks(result: RunResult) -> list:
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


def _send_notifications(config: WorkflowConfig, result: RunResult) -> None:
    settings = config.notifications
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
        project=config.project.name,
        succeeded=result.succeeded,
        cancelled=result.cancelled,
        duration_seconds=result.duration_seconds,
        counts=result.counts,
        failed_tasks=_failed_tasks(result),
    )
    try:
        delivered = notifier.send(notification)
    except Exception as exc:  # defensive: never break the run
        _err(sys.stderr, "warning: notification failed: %s" % type(exc).__name__)
        return
    if not delivered:
        _err(sys.stderr, "warning: notification was not delivered")


def cmd_history(args: argparse.Namespace) -> int:
    try:
        config = _load(args)
        root = config.project.root
        max_runs = config.history.max_runs
    except ConfigError:
        root = Path.cwd()
        max_runs = 500
    store = HistoryStore(root, max_runs=max_runs)
    try:
        runs = store.recent(limit=args.limit)
    finally:
        store.close()
    if args.json:
        print(json.dumps(runs, indent=2))
        return EXIT_OK
    if not runs:
        print("No execution history recorded.")
        return EXIT_OK
    for run in runs:
        status = "ok" if run["succeeded"] else "failed"
        print(
            "%s  %-6s  %6.2fs  %s"
            % (run["run_id"], status, run["duration_seconds"], run["project"])
        )
    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        _err(sys.stderr, str(exc))
        return EXIT_USAGE
    except GraphError as exc:
        _err(sys.stderr, str(exc))
        return EXIT_GRAPH
    except PyTaskWireCheckError as exc:
        _err(sys.stderr, str(exc))
        return EXIT_USAGE
    except BrokenPipeError:  # pragma: no cover
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
