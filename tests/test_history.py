"""Execution history tests."""

from __future__ import annotations

import json
import sys

from pytaskwirecheck.cli import EXIT_OK, main
from pytaskwirecheck.diagnostics.errors import HistoryError
from pytaskwirecheck.engine.cancellation import CancellationToken
from pytaskwirecheck.engine.events import EventBus
from pytaskwirecheck.engine.executor import TaskExecutor
from pytaskwirecheck.engine.scheduler import Scheduler
from pytaskwirecheck.graph.builder import build_graph
from pytaskwirecheck.graph.planner import resolve_targets
from pytaskwirecheck.graph.validator import validate_graph
from pytaskwirecheck.history.store import HistoryStore

PY = sys.executable

GOOD = f"""
[project]
name = "hist"
version = 1

[tasks.a]
command = ["{PY}", "-c", "print('a')"]
"""


def _run(tmp_path):
    config_path = tmp_path / "pytaskwirecheck.toml"
    config_path.write_text(GOOD)
    from pytaskwirecheck.config.loader import load_config

    config = load_config(config_path)
    graph = build_graph(config)
    validate_graph(graph)
    events = EventBus()
    token = CancellationToken()
    executor = TaskExecutor(
        root=config.project.root,
        default_timeout=None,
        events=events,
        cancel_token=token,
        base_env={},
    )
    scheduler = Scheduler(
        graph=graph,
        execution=config.execution,
        executor=executor,
        events=events,
        cancel_token=token,
    )
    return scheduler.run(resolve_targets(graph, []), run_id="fixedrun123")


def test_record_and_read(tmp_path):
    result = _run(tmp_path)
    store = HistoryStore(tmp_path)
    store.record_run(result, project="hist", config_version=1)
    runs = store.recent(limit=10)
    store.close()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "fixedrun123"
    assert runs[0]["succeeded"] is True


def test_prune_respects_max_runs(tmp_path):
    store = HistoryStore(tmp_path, max_runs=2)
    for index in range(4):
        result = _run(tmp_path)
        result.run_id = "run%d" % index
        store.record_run(result, project="hist", config_version=1)
    runs = store.recent(limit=100)
    store.close()
    assert len(runs) == 2


def test_history_cli(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK
    capsys.readouterr()
    assert main(["history", "--json"]) == EXIT_OK
    runs = json.loads(capsys.readouterr().out)
    assert len(runs) == 1
    assert runs[0]["project"] == "hist"


def test_history_write_failure_does_not_change_exit(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    monkeypatch.chdir(tmp_path)

    class _Boom(HistoryStore):
        def record_run(self, *args, **kwargs):
            raise HistoryError("disk on fire")

    monkeypatch.setattr("pytaskwirecheck.cli.HistoryStore", _Boom)
    assert main(["run", "--quiet"]) == EXIT_OK
    assert "disk on fire" in capsys.readouterr().err


def test_history_disabled(monkeypatch, tmp_path):
    (tmp_path / "pytaskwirecheck.toml").write_text(
        GOOD + "\n[history]\nenabled = false\n"
    )
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK
    assert not (tmp_path / ".pytaskwirecheck" / "history.db").exists()


def test_history_without_config(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["history"]) == EXIT_OK
    assert "No execution history" in capsys.readouterr().out
