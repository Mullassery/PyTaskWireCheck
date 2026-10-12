"""End-to-end integration tests running real commands in temporary projects."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pytaskwirecheck.cli import EXIT_OK, main

PY = sys.executable


def _config(tmp_path: Path, text: str) -> None:
    (tmp_path / "pytaskwirecheck.toml").write_text(text, encoding="utf-8")


def test_pipeline_produces_outputs(monkeypatch, tmp_path, capsys):
    _config(
        tmp_path,
        f"""
[project]
name = "pipeline"
version = 1

[execution]
max_workers = 4

[tasks.generate]
command = ["{PY}", "-c", "open('data.txt','w').write('hello')"]
inputs = []
outputs = ["data.txt"]

[tasks.transform]
command = ["{PY}", "-c", "open('upper.txt','w').write(open('data.txt').read().upper())"]
depends_on = ["generate"]
inputs = ["data.txt"]
outputs = ["upper.txt"]
""",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["succeeded"] is True
    assert (tmp_path / "data.txt").read_text() == "hello"
    assert (tmp_path / "upper.txt").read_text() == "HELLO"
    assert payload["counts"]["succeeded"] == 2


def test_independent_branches_run_concurrently(monkeypatch, tmp_path, capsys):
    body = (
        "import time,pathlib; s=time.time(); time.sleep(1.0); "
        "pathlib.Path('w{name}.txt').write_text('%f,%f' % (s, time.time()))"
    )
    _config(
        tmp_path,
        f"""
[execution]
max_workers = 3

[tasks.x]
command = ["{PY}", "-c", "{body.format(name="x")}"]
[tasks.y]
command = ["{PY}", "-c", "{body.format(name="y")}"]
[tasks.z]
command = ["{PY}", "-c", "{body.format(name="z")}"]
""",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK
    windows = []
    for name in ("x", "y", "z"):
        start, end = (tmp_path / f"w{name}.txt").read_text().split(",")
        windows.append((float(start), float(end)))
    overlaps = sum(
        1
        for i in range(len(windows))
        for j in range(i + 1, len(windows))
        if min(windows[i][1], windows[j][1]) - max(windows[i][0], windows[j][0]) > 0.3
    )
    assert overlaps >= 2, "expected concurrent, overlapping task windows"


def test_noninteractive_pipeline(monkeypatch, tmp_path, capsys):
    _config(
        tmp_path,
        f"""
[tasks.only]
command = ["{PY}", "-c", "print('ci')"]
""",
    )
    monkeypatch.chdir(tmp_path)
    # --no-output keeps CI logs terse; --json is fully machine-readable.
    assert main(["run", "--json", "--no-output"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["tasks"]["only"]["status"] == "succeeded"


def test_failure_reports_downstream_blocked(monkeypatch, tmp_path, capsys):
    _config(
        tmp_path,
        f"""
[tasks.fail]
command = ["{PY}", "-c", "import sys; sys.exit(1)"]
[tasks.after]
command = ["{PY}", "-c", "print('no')"]
depends_on = ["fail"]
""",
    )
    monkeypatch.chdir(tmp_path)
    rc = main(["run", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc != 0
    assert payload["tasks"]["fail"]["status"] == "failed"
    assert payload["tasks"]["after"]["status"] == "blocked"
