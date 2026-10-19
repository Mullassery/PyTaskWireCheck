"""Watch mode tests inject a fake watchfiles.watch (no real waiting)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

from pytaskwirecheck.cli import main

CONFIG = """
[project]
name = "watch-demo"
version = 1

[execution]
max_workers = 1

[tasks.build]
command = ["python", "-c", "print('build')"]
inputs = ["src/**"]

[tasks.test]
command = ["python", "-c", "print('test')"]
depends_on = ["build"]
inputs = ["src/**"]
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    (tmp_path / "pytaskwirecheck.toml").write_text(CONFIG)
    return tmp_path


def test_watch_runs_affected_tasks_and_stops(monkeypatch, tmp_path):
    root = _project(tmp_path)
    calls = []

    def fake_watch(path, debounce=300):
        calls.append((path, debounce))
        yield {(1, root / "src" / "app.py")}
        raise KeyboardInterrupt

    module = types.ModuleType("watchfiles")
    module.watch = fake_watch
    monkeypatch.setitem(sys.modules, "watchfiles", module)

    code = main(
        ["--config", str(root / "pytaskwirecheck.toml"), "watch", "--debounce-ms", "50"]
    )
    assert code == 130
    assert calls == [(root.resolve(), 50)]


def test_missing_watchfiles_is_actionable(monkeypatch, tmp_path, capsys):
    root = _project(tmp_path)
    monkeypatch.setitem(sys.modules, "watchfiles", None)
    code = main(["--config", str(root / "pytaskwirecheck.toml"), "watch"])
    assert code == 2
    assert "pytaskwirecheck[watch]" in capsys.readouterr().err
