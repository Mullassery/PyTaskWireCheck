"""Tests for the optional live dashboard (:mod:`pytaskwirecheck.tui.app`)."""

from __future__ import annotations

import io
import re

from pytaskwirecheck.engine.events import RunFinished, RunStarted, TaskStateChanged
from pytaskwirecheck.engine.state import TaskStatus
from pytaskwirecheck.tui.app import LiveDashboard

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class _TTY(io.StringIO):
    def isatty(self) -> bool:  # noqa: D401 - test double
        return True


def _feed(dashboard: LiveDashboard) -> None:
    dashboard.handle(RunStarted(run_id="abc123", tasks=("a", "b"), total_tasks=2))
    dashboard.handle(TaskStateChanged(task_id="a", status=TaskStatus.RUNNING))
    dashboard.handle(TaskStateChanged(task_id="a", status=TaskStatus.SUCCEEDED))
    dashboard.handle(
        TaskStateChanged(
            task_id="b",
            status=TaskStatus.FAILED,
            message="exit code 1",
        )
    )
    dashboard.handle(RunFinished(run_id="abc123", succeeded=False, summary={}))


def test_render_reflects_events():
    dashboard = LiveDashboard(_TTY())
    _feed(dashboard)
    rendered = dashboard._render()
    assert "abc123" in rendered
    assert "2/2 done" in rendered
    assert "a" in rendered and "b" in rendered
    assert "exit code 1" in rendered


def test_render_truncates_to_terminal_size(monkeypatch):
    monkeypatch.setenv("LINES", "8")
    monkeypatch.setenv("COLUMNS", "40")
    dashboard = LiveDashboard(_TTY())
    dashboard.handle(
        RunStarted(
            run_id="r", tasks=tuple("t%d" % i for i in range(30)), total_tasks=30
        )
    )
    rendered = dashboard._render()
    assert "more)" in rendered
    for line in _ANSI.sub("", rendered).splitlines():
        assert len(line) <= 40


def test_start_noop_when_not_a_tty():
    dashboard = LiveDashboard(io.StringIO())
    dashboard.start()
    assert dashboard._thread is None
    dashboard.stop()  # must be safe and write nothing


def test_start_noop_when_isatty_raises():
    class _Broken(io.StringIO):
        def isatty(self):  # noqa: D401 - test double
            raise ValueError("detached")

    dashboard = LiveDashboard(_Broken())
    dashboard.start()
    assert dashboard._thread is None
    dashboard.stop()


def test_start_and_stop_on_tty():
    dashboard = LiveDashboard(_TTY(), refresh_interval=10.0)
    dashboard.start()
    assert dashboard._thread is not None
    _feed(dashboard)
    dashboard.stop()
    assert dashboard._thread is None


def test_write_swallows_broken_pipe():
    class _Closed(io.StringIO):
        def write(self, _text):  # noqa: D401 - test double
            raise BrokenPipeError

    dashboard = LiveDashboard(_Closed())
    dashboard._write("ignored")  # must not raise
