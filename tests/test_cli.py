"""CLI behaviour tests (invoked in-process against temporary projects)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pytaskwirecheck.cli import (
    EXIT_GRAPH,
    EXIT_OK,
    EXIT_TASK_FAILURE,
    EXIT_USAGE,
    main,
)

PY = sys.executable

GOOD = f"""
[project]
name = "demo"
version = 1

[tasks.a]
command = ["{PY}", "-c", "print('a')"]

[tasks.b]
command = ["{PY}", "-c", "print('b')"]
depends_on = ["a"]
"""


def _chdir(monkeypatch, path: Path):
    monkeypatch.chdir(path)


def test_init_creates_config(monkeypatch, tmp_path):
    _chdir(monkeypatch, tmp_path)
    assert main(["init"]) == EXIT_OK
    assert (tmp_path / "pytaskwirecheck.toml").is_file()


def test_init_refuses_overwrite(monkeypatch, tmp_path):
    _chdir(monkeypatch, tmp_path)
    assert main(["init"]) == EXIT_OK
    assert main(["init"]) == EXIT_USAGE
    assert main(["init", "--force"]) == EXIT_OK


def test_validate_good(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["validate"]) == EXIT_OK
    assert "configuration OK" in capsys.readouterr().out


def test_validate_bad(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text("[tasks.a]\ncommand = 'nope'\n")
    _chdir(monkeypatch, tmp_path)
    assert main(["validate"]) == EXIT_USAGE
    assert "error" in capsys.readouterr().err


def test_validate_missing_config(monkeypatch, tmp_path, capsys):
    _chdir(monkeypatch, tmp_path)
    assert main(["validate"]) == EXIT_USAGE
    assert "no pytaskwirecheck.toml" in capsys.readouterr().err


def test_graph_text(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["graph"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "a -> b" in out


def test_graph_dot(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["graph", "--format", "dot"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "digraph" in out and '"a" -> "b"' in out


def test_graph_json(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["graph", "--format", "json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["tasks"]["b"]["depends_on"] == ["a"]


def test_cycle_returns_graph_error(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(
        f"""
[tasks.a]
command = ["{PY}", "-c", "pass"]
depends_on = ["b"]
[tasks.b]
command = ["{PY}", "-c", "pass"]
depends_on = ["a"]
"""
    )
    _chdir(monkeypatch, tmp_path)
    assert main(["validate"]) == EXIT_GRAPH
    assert "cycle" in capsys.readouterr().err


def test_plan_json(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["plan", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["order"] == ["a", "b"]


def test_run_success(monkeypatch, tmp_path):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK


def test_run_subset(monkeypatch, tmp_path):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "a", "--quiet"]) == EXIT_OK


def test_run_unknown_task(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "ghost"]) == EXIT_GRAPH
    assert "unknown task" in capsys.readouterr().err


def test_run_failure_exit_code(monkeypatch, tmp_path):
    (tmp_path / "pytaskwirecheck.toml").write_text(
        f"""
[tasks.a]
command = ["{PY}", "-c", "import sys; sys.exit(1)"]
"""
    )
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "--quiet"]) == EXIT_TASK_FAILURE


def test_run_json_summary(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["succeeded"] is True
    assert payload["tasks"]["a"]["status"] == "succeeded"


def test_run_creates_logs(monkeypatch, tmp_path):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK
    logs = tmp_path / ".pytaskwirecheck" / "logs"
    assert logs.is_dir()
    assert list(logs.iterdir())


CACHEABLE = f"""
[tasks.build]
command = ["{PY}", "-c", "import pathlib; p=pathlib.Path('count'); c=int(p.read_text()) if p.exists() else 0; p.write_text(str(c+1)); open('out.txt','w').write('x')"]
outputs = ["out.txt"]
"""


def test_cache_status_cli(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(CACHEABLE)
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK
    capsys.readouterr()
    assert main(["cache", "status", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"] == 1


def test_second_run_is_cached(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(CACHEABLE)
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK
    capsys.readouterr()
    assert main(["run", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["tasks"]["build"]["status"] == "cached"
    assert (tmp_path / "count").read_text() == "1"


def test_cache_clean_requires_force(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(CACHEABLE)
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK
    assert main(["cache", "clean"]) == EXIT_USAGE
    assert main(["cache", "clean", "--force"]) == EXIT_OK
    capsys.readouterr()
    assert main(["cache", "status", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"] == 0


def test_no_cache_bypasses(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(CACHEABLE)
    _chdir(monkeypatch, tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK
    assert main(["run", "--quiet", "--no-cache"]) == EXIT_OK
    assert (tmp_path / "count").read_text() == "2"


def test_explain_json(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["explain", "b", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["task"] == "b"
    assert payload["depends_on"] == ["a"]


def test_explain_unknown_task(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(GOOD)
    _chdir(monkeypatch, tmp_path)
    assert main(["explain", "ghost"]) == EXIT_GRAPH
