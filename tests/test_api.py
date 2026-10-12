"""Tests for the high-level Python API (:mod:`pytaskwirecheck.api`)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import pytaskwirecheck
from pytaskwirecheck import Workflow
from pytaskwirecheck.diagnostics.errors import ConfigError, GraphError
from pytaskwirecheck.engine.events import RunFinished, RunStarted, TaskStateChanged

PY = sys.executable


def _workflow(tmp_path: Path, body: str) -> Workflow:
    return Workflow.from_text(body, root=tmp_path)


def test_public_exports_are_available():
    for name in ("Workflow", "load_workflow", "validate", "plan", "run"):
        assert hasattr(pytaskwirecheck, name)


def test_from_text_validate_and_plan(tmp_path):
    workflow = _workflow(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "print('a')"]
        [tasks.b]
        depends_on = ["a"]
        command = ["{PY}", "-c", "print('b')"]
        """,
    )
    plan = workflow.validate()
    assert [list(level) for level in plan.levels] == [["a"], ["b"]]
    assert workflow.plan(["b"]).order == ("a", "b")


def test_run_executes_all_tasks(tmp_path):
    workflow = _workflow(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "print('a')"]
        [tasks.b]
        depends_on = ["a"]
        command = ["{PY}", "-c", "print('b')"]
        """,
    )
    result = workflow.run(record_history=False, notify=False)
    assert result.succeeded
    assert sorted(result.records) == ["a", "b"]
    assert all(r.status.is_success for r in result.records.values())


def test_run_restricts_to_targets_and_dependencies(tmp_path):
    workflow = _workflow(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "print('a')"]
        [tasks.b]
        depends_on = ["a"]
        command = ["{PY}", "-c", "print('b')"]
        [tasks.c]
        command = ["{PY}", "-c", "print('c')"]
        """,
    )
    result = workflow.run(["b"], record_history=False, notify=False)
    assert result.succeeded
    assert sorted(result.records) == ["a", "b"]


def test_run_reports_failure(tmp_path):
    workflow = _workflow(
        tmp_path,
        f"""
        [tasks.bad]
        command = ["{PY}", "-c", "import sys; sys.exit(3)"]
        """,
    )
    result = workflow.run(record_history=False, notify=False)
    assert not result.succeeded
    assert result.records["bad"].exit_code == 3


def test_run_emits_events(tmp_path):
    workflow = _workflow(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "print('a')"]
        """,
    )
    seen = []
    workflow.run(on_event=seen.append, record_history=False, notify=False)
    kinds = {type(event).__name__ for event in seen}
    assert RunStarted.__name__ in kinds
    assert RunFinished.__name__ in kinds
    assert TaskStateChanged.__name__ in kinds


def test_run_max_workers_override_validation(tmp_path):
    workflow = _workflow(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "print('a')"]
        """,
    )
    with pytest.raises(ConfigError):
        workflow.run(max_workers=0, record_history=False, notify=False)


def test_precancelled_token_produces_cancelled_result(tmp_path):
    workflow = _workflow(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "print('a')"]
        """,
    )
    token = pytaskwirecheck.api.CancellationToken()
    token.cancel("test")
    result = workflow.run(cancel_token=token, record_history=False, notify=False)
    assert not result.succeeded


def test_unknown_target_raises_graph_error(tmp_path):
    workflow = _workflow(
        tmp_path,
        f"""
        [tasks.a]
        command = ["{PY}", "-c", "print('a')"]
        """,
    )
    with pytest.raises(GraphError):
        workflow.run(["missing"], record_history=False, notify=False)


def test_from_file_missing_config_raises(tmp_path):
    with pytest.raises(ConfigError):
        Workflow.from_file(tmp_path / "nope.toml")


def test_functional_run_convenience(tmp_path):
    config = tmp_path / "pytaskwirecheck.toml"
    config.write_text(
        f'[tasks.hello]\ncommand = ["{PY}", "-c", "print(1)"]\n',
        encoding="utf-8",
    )
    result = pytaskwirecheck.run(path=config, record_history=False, notify=False)
    assert result.succeeded
    assert pytaskwirecheck.validate(path=config).order == ("hello",)
    assert pytaskwirecheck.plan(path=config) == pytaskwirecheck.validate(path=config)
