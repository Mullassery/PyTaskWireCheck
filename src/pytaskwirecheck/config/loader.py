"""Configuration file discovery, parsing, and loading.

This module performs I/O only to *read* configuration. It never executes tasks
or performs network access. Discovery walks upward from a starting directory to
locate ``pytaskwirecheck.toml``, mirroring common tooling conventions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.9/3.10
    import tomli as _toml

from pytaskwirecheck.config.schema import WorkflowConfig
from pytaskwirecheck.config.validation import build_workflow, normalize_root
from pytaskwirecheck.diagnostics.errors import ConfigError

CONFIG_FILENAME = "pytaskwirecheck.toml"
STATE_DIRNAME = ".pytaskwirecheck"


def find_config(start: Path) -> Optional[Path]:
    """Return the nearest ``pytaskwirecheck.toml`` at or above ``start``, if any."""
    current = start.resolve()
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def parse_toml(text: str, *, location: str) -> Dict[str, Any]:
    """Parse TOML text into a dict, raising :class:`ConfigError` on failure."""
    try:
        return _toml.loads(text)
    except Exception as exc:  # tomllib/tomli raise TOMLDecodeError
        raise ConfigError("invalid TOML: %s" % exc, location=location) from exc


def load_config(
    config_path: Path, *, root_override: Optional[str] = None
) -> WorkflowConfig:
    """Load and validate a workflow configuration from ``config_path``."""
    config_path = config_path.resolve()
    if not config_path.is_file():
        raise ConfigError("configuration file not found: %s" % config_path)

    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("cannot read %s: %s" % (config_path, exc)) from exc

    raw = parse_toml(text, location=str(config_path))

    # Default root is the directory holding the config file; CLI overrides are
    # constrained to remain inside the current working directory.
    base = Path(os.getcwd())
    if root_override is not None:
        root = normalize_root(root_override, base)
    else:
        root = config_path.parent.resolve()
    return build_workflow(raw, root, config_path)


def state_dir(root: Path) -> Path:
    """Return the (possibly non-existent) PyTaskWireCheck state directory for a root."""
    return root / STATE_DIRNAME
