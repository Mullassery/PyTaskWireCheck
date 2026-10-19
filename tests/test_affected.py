"""Affected-task selection tests."""

from pytaskwirecheck.config.loader import load_config
from pytaskwirecheck.graph.affected import affected_tasks
from pytaskwirecheck.graph.builder import build_graph

CONFIG = """
[project]
name = "affected"
version = 1

[tasks.build]
command = ["true"]
inputs = ["src/**/*.py"]
outputs = ["out.txt"]

[tasks.test]
command = ["true"]
depends_on = ["build"]
inputs = ["tests/**/*.py"]
outputs = ["test.txt"]

[tasks.docs]
command = ["true"]
inputs = ["docs/**/*.md"]
outputs = ["docs.txt"]
"""


def _graph(tmp_path):
    path = tmp_path / "pytaskwirecheck.toml"
    path.write_text(CONFIG)
    config = load_config(path)
    return build_graph(config)


def test_changed_source_pulls_dependents(tmp_path):
    graph = _graph(tmp_path)
    assert affected_tasks(graph, {"src/main.py"}) == {"build", "test"}


def test_changed_test_file_runs_test_only(tmp_path):
    graph = _graph(tmp_path)
    assert affected_tasks(graph, {"tests/test_x.py"}) == {"test"}


def test_no_matching_changes_is_empty(tmp_path):
    graph = _graph(tmp_path)
    assert affected_tasks(graph, {"README.md"}) == set()
