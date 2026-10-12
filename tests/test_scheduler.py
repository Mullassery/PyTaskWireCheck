"""Scheduler tests: ordering, concurrency, failure policy, retries, timeouts."""

from __future__ import annotations

import sys
import textwrap
import threading
import time
from pathlib import Path

from pytaskwirecheck.config.loader import load_config
from pytaskwirecheck.config.schema import ExecutionConfig
from pytaskwirecheck.engine.cancellation import CancellationToken
from pytaskwirecheck.engine.events import EventBus
from pytaskwirecheck.engine.executor import TaskExecutor, TaskOutcome
from pytaskwirecheck.engine.scheduler import Scheduler
from pytaskwirecheck.engine.state import TaskStatus
from pytaskwirecheck.graph.builder import build_graph
from pytaskwirecheck.graph.planner import resolve_targets
from pytaskwirecheck.graph.validator import validate_graph

PY = sys.executable


def _write_config(tmp_path: Path, text: str):
    path = tmp_path / "pytaskwirecheck.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return load_config(path)


def _run(
    tmp_path,
    text,
    *,
    targets=None,
    max_workers=1,
    fail_fast=False,
    default_timeout=None,
    cancel_token=None,
    executor=None,
):
    config = _write_config(tmp_path, text)
    graph = build_graph(config)
    validate_graph(graph)
    selected = resolve_targets(graph, targets or [])
    events = EventBus()
    token = cancel_token or CancellationToken()
    execution = ExecutionConfig(
        max_workers=max_workers,
        fail_fast=fail_fast,
        default_timeout_seconds=default_timeout,
    )
    if executor is None:
        executor = TaskExecutor(
            root=config.project.root,
            default_timeout=default_timeout,
            events=events,
            cancel_token=token,
            base_env={"PATH": "/usr/bin:/bin"},
        )
    scheduler = Scheduler(
        graph=graph,
        execution=execution,
        executor=executor,
        events=events,
        cancel_token=token,
    )
    return scheduler.run(selected)


def test_dependency_ordering(tmp_path):
    result = _run(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "open('order','a').write('a')"]
        [tasks.b]
        command = ["{PY}", "-c", "open('order','a').write('b')"]
        depends_on = ["a"]
        """,
    )
    assert result.succeeded
    assert (tmp_path / "order").read_text() == "ab"


def test_parallel_execution(tmp_path):
    # Each task records its own [start, end] window; parallel execution is
    # proven by window overlap rather than by wall-clock thresholds, which are
    # unreliable on loaded CI machines.
    task_body = (
        "import time,pathlib; s=time.time(); time.sleep(1.0); "
        "pathlib.Path('w{name}.txt').write_text('%f,%f' % (s, time.time()))"
    )
    text = f"""
    [execution]
    max_workers = 3
    [tasks.a]
    command = ["{PY}", "-c", "{task_body.format(name="a")}"]
    [tasks.b]
    command = ["{PY}", "-c", "{task_body.format(name="b")}"]
    [tasks.c]
    command = ["{PY}", "-c", "{task_body.format(name="c")}"]
    """
    result = _run(tmp_path, text, max_workers=3)
    assert result.succeeded
    windows = []
    for name in ("a", "b", "c"):
        start, end = (tmp_path / f"w{name}.txt").read_text().split(",")
        windows.append((float(start), float(end)))
    overlaps = 0
    for i in range(len(windows)):
        for j in range(i + 1, len(windows)):
            overlap = min(windows[i][1], windows[j][1]) - max(
                windows[i][0], windows[j][0]
            )
            if overlap > 0.3:
                overlaps += 1
    assert overlaps >= 2, "expected at least two overlapping task windows"


def test_worker_limit_is_respected(tmp_path):
    text = f"""
    [tasks.a]
    command = ["{PY}", "-c", "import time; time.sleep(0.6)"]
    [tasks.b]
    command = ["{PY}", "-c", "import time; time.sleep(0.6)"]
    """
    start = time.monotonic()
    result = _run(tmp_path, text, max_workers=1)
    elapsed = time.monotonic() - start
    assert result.succeeded
    assert elapsed >= 1.0


def test_failure_blocks_dependents(tmp_path):
    result = _run(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "import sys; sys.exit(2)"]
        [tasks.b]
        command = ["{PY}", "-c", "print('never')"]
        depends_on = ["a"]
        """,
    )
    assert not result.succeeded
    assert result.records["a"].status is TaskStatus.FAILED
    assert result.records["b"].status is TaskStatus.BLOCKED


def test_unrelated_branch_continues(tmp_path):
    result = _run(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "import sys; sys.exit(2)"]
        [tasks.b]
        command = ["{PY}", "-c", "print('x')"]
        depends_on = ["a"]
        [tasks.c]
        command = ["{PY}", "-c", "print('c')"]
        [tasks.d]
        command = ["{PY}", "-c", "print('d')"]
        depends_on = ["c"]
        """,
        max_workers=1,
        fail_fast=False,
    )
    assert result.records["a"].status is TaskStatus.FAILED
    assert result.records["b"].status is TaskStatus.BLOCKED
    assert result.records["c"].status is TaskStatus.SUCCEEDED
    assert result.records["d"].status is TaskStatus.SUCCEEDED


def test_fail_fast_stops_scheduling(tmp_path):
    result = _run(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "import sys; sys.exit(2)"]
        [tasks.c]
        command = ["{PY}", "-c", "print('c')"]
        """,
        max_workers=1,
        fail_fast=True,
    )
    assert result.records["a"].status is TaskStatus.FAILED
    assert result.records["c"].status is TaskStatus.CANCELLED


def test_timeout_marks_timed_out(tmp_path):
    result = _run(
        tmp_path,
        f"""
        [tasks.slow]
        command = ["{PY}", "-c", "import time; time.sleep(30)"]
        timeout_seconds = 0.5
        """,
    )
    assert result.records["slow"].status is TaskStatus.TIMED_OUT
    assert not result.succeeded


def test_retry_eventually_succeeds(tmp_path):
    script = (
        "import pathlib,sys; p=pathlib.Path('counter'); "
        "n=int(p.read_text()) if p.exists() else 0; n+=1; "
        "p.write_text(str(n)); sys.exit(0 if n>=3 else 1)"
    )
    result = _run(
        tmp_path,
        f"""
        [tasks.flaky]
        command = ["{PY}", "-c", "{script}"]
        [tasks.flaky.retry]
        max_attempts = 3
        delay_seconds = 0.05
        """,
    )
    assert result.records["flaky"].status is TaskStatus.SUCCEEDED
    assert result.records["flaky"].attempt == 3


def test_no_retry_by_default(tmp_path):
    script = (
        "import pathlib,sys; p=pathlib.Path('counter2'); "
        "n=int(p.read_text()) if p.exists() else 0; n+=1; "
        "p.write_text(str(n)); sys.exit(1)"
    )
    result = _run(
        tmp_path,
        f"""
        [tasks.fail]
        command = ["{PY}", "-c", "{script}"]
        """,
    )
    assert result.records["fail"].status is TaskStatus.FAILED
    assert result.records["fail"].attempt == 1


def test_cancellation(tmp_path):
    token = CancellationToken()
    config_text = f"""
    [tasks.slow]
    command = ["{PY}", "-c", "import time; time.sleep(30)"]
    """

    def canceller():
        time.sleep(0.4)
        token.cancel("test stop")

    thread = threading.Thread(target=canceller)
    thread.start()
    start = time.monotonic()
    result = _run(tmp_path, config_text, cancel_token=token)
    thread.join()
    assert time.monotonic() - start < 10
    assert result.records["slow"].status is TaskStatus.CANCELLED


class _ExplodingExecutor:
    def __init__(self, root):
        self._root = root

    def execute(self, task, dependency_keys=None, *, use_cache=True):
        if task.id == "boom":
            raise RuntimeError("kaboom")
        return TaskOutcome(task_id=task.id, status=TaskStatus.SUCCEEDED)


def test_scheduler_survives_executor_exception(tmp_path):
    result = _run(
        tmp_path,
        """
        [tasks.boom]
        command = ["true"]
        [tasks.ok]
        command = ["true"]
        """,
        executor=_ExplodingExecutor(tmp_path),
        max_workers=1,
    )
    assert result.records["boom"].status is TaskStatus.FAILED
    assert result.records["ok"].status is TaskStatus.SUCCEEDED
