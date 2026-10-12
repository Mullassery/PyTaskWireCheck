"""Content-addressed cache fingerprinting.

The fingerprint captures everything PyTaskWireCheck knows can affect a task's result:
its command, shell mode, working directory, declared inputs (by content), the
cache keys of its declared dependencies, relevant environment variables (hashed,
never stored in plaintext), and a small runtime identity.

Anything *not* declared is, by definition, invisible to the cache. Tasks that
depend on undeclared files, the network, the clock, or other nondeterminism may
receive incorrect cache hits; see ``docs/caching.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pytaskwirecheck.config.schema import DEFAULT_RELEVANT_ENV, TaskConfig

#: Bump when the fingerprint algorithm or payload shape changes incompatibly.
CACHE_SCHEMA_VERSION = 1

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class InputFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Fingerprint:
    """The cache key plus the information needed to explain a hit or miss."""

    key: str
    payload: dict
    inputs: Tuple[InputFile, ...]
    missing_patterns: Tuple[str, ...]
    env_names: Tuple[str, ...]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_iter_files(root: Path, base: Path) -> Iterable[Path]:
    """Yield regular files under ``base`` (a file or directory)."""
    if base.is_file():
        yield base
        return
    if base.is_dir():
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in sorted(filenames):
                candidate = Path(dirpath) / name
                if candidate.is_file() and not candidate.is_symlink():
                    yield candidate


def expand_inputs(
    root: Path, patterns: Sequence[str]
) -> Tuple[List[InputFile], List[str]]:
    """Expand input globs into a sorted list of hashed files.

    Returns the hashed files and the patterns that matched nothing.
    """
    root = root.resolve()
    seen: Dict[str, InputFile] = {}
    missing: List[str] = []
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        matched_any = False
        for match in matches:
            if match.is_dir():
                files = list(_safe_iter_files(root, match))
                if files:
                    matched_any = True
            else:
                files = [match]
                matched_any = True
            for file_path in files:
                try:
                    rel = file_path.resolve().relative_to(root).as_posix()
                except ValueError:
                    continue
                if rel in seen:
                    continue
                try:
                    size = file_path.stat().st_size
                    digest = hash_file(file_path)
                except OSError:
                    continue
                seen[rel] = InputFile(path=rel, sha256=digest, size=size)
        if not matched_any:
            missing.append(pattern)
    return [seen[key] for key in sorted(seen)], missing


def _hash_env_values(values: Mapping[str, str]) -> Dict[str, str]:
    return {
        name: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for name, value in sorted(values.items())
    }


def build_effective_env(
    task: TaskConfig, base_env: Mapping[str, str]
) -> Dict[str, str]:
    env = dict(base_env) if task.inherit_env else {}
    env.update(task.env)
    return env


def compute_fingerprint(
    task: TaskConfig,
    root: Path,
    dependency_keys: Mapping[str, Optional[str]],
    *,
    base_env: Optional[Mapping[str, str]] = None,
    relevant_env: Sequence[str] = DEFAULT_RELEVANT_ENV,
) -> Fingerprint:
    """Compute the cache fingerprint for ``task``."""
    base_env = base_env if base_env is not None else os.environ
    effective_env = build_effective_env(task, base_env)

    relevant_names = sorted(set(relevant_env) | set(task.env.keys()))
    selected_env = {
        name: effective_env[name] for name in relevant_names if name in effective_env
    }
    hashed_env = _hash_env_values(selected_env)

    inputs, missing = expand_inputs(root, task.inputs)

    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "task_id": task.id,
        "command": list(task.command),
        "shell": task.shell,
        "cwd": task.cwd or ".",
        "timeout_seconds": task.timeout_seconds,
        "env": hashed_env,
        "input_patterns": list(task.inputs),
        "inputs": [
            {"path": f.path, "sha256": f.sha256, "size": f.size} for f in inputs
        ],
        "outputs": list(task.outputs),
        "dependencies": {name: key for name, key in sorted(dependency_keys.items())},
        "runtime": {
            "python": "%d.%d.%d" % sys.version_info[:3],
            "platform": sys.platform,
            "machine": platform.machine(),
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Fingerprint(
        key=key,
        payload=payload,
        inputs=tuple(inputs),
        missing_patterns=tuple(missing),
        env_names=tuple(sorted(selected_env.keys())),
    )
