"""Shared test fixtures and helpers."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Callable

import pytest

from pytaskwirecheck.config.loader import load_config
from pytaskwirecheck.config.schema import WorkflowConfig


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[..., WorkflowConfig]:
    """Return a factory that writes a config file and loads it."""

    def _make(text: str, *, filename: str = "pytaskwirecheck.toml") -> WorkflowConfig:
        path = tmp_path / filename
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return load_config(path)

    return _make


@pytest.fixture
def make_config_file(tmp_path: Path) -> Callable[..., Path]:
    def _make(text: str, *, filename: str = "pytaskwirecheck.toml") -> Path:
        path = tmp_path / filename
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return path

    return _make
