"""Strict validation helpers that turn raw configuration dicts into the typed
:mod:`pytaskwirecheck.config.schema` model.

The guiding rule is: never silently reinterpret invalid configuration. Unknown
fields, wrong types, out-of-workspace paths, and unsupported versions all raise
:class:`~pytaskwirecheck.diagnostics.errors.ConfigError` with an actionable location.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pytaskwirecheck.config.schema import (
    DEFAULT_CONFIG_VERSION,
    DEFAULT_RELEVANT_ENV,
    MAX_WORKERS_LIMIT,
    SUPPORTED_CONFIG_VERSIONS,
    CacheConfig,
    ExecutionConfig,
    HistoryConfig,
    NotificationsConfig,
    ProjectConfig,
    ResourceLimits,
    RetryPolicy,
    TaskConfig,
    WorkflowConfig,
)
from pytaskwirecheck.diagnostics.errors import ConfigError, ConfigVersionError

_TOP_LEVEL_KEYS = {
    "project",
    "execution",
    "tasks",
    "cache",
    "history",
    "notifications",
}
_PROJECT_KEYS = {"name", "version", "root"}
_EXECUTION_KEYS = {
    "max_workers",
    "default_timeout_seconds",
    "fail_fast",
}
_CACHE_KEYS = {"enabled", "relevant_env", "max_bytes", "max_entries"}
_HISTORY_KEYS = {"enabled", "max_runs"}
_NOTIFICATIONS_KEYS = {"enabled", "url", "timeout_seconds", "max_attempts", "on"}
_TASK_KEYS = {
    "command",
    "depends_on",
    "inputs",
    "outputs",
    "cache",
    "cwd",
    "env",
    "inherit_env",
    "timeout_seconds",
    "retries",
    "retry",
    "shell",
    "description",
    "max_output_bytes",
}
_RETRY_KEYS = {
    "max_attempts",
    "delay_seconds",
    "backoff",
    "max_delay_seconds",
    "retry_on_exit_codes",
}

_VALID_TASK_ID = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)


def _reject_unknown(
    table: Mapping[str, Any],
    allowed: set,
    location: str,
    *,
    task: Optional[str] = None,
) -> None:
    unknown = sorted(set(table.keys()) - allowed)
    if unknown:
        raise ConfigError(
            "unknown field(s): %s" % ", ".join(unknown),
            location=location,
            task=task,
        )


def _require_table(
    value: Any, location: str, *, task: Optional[str] = None
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(
            "expected a table, got %s" % type(value).__name__,
            location=location,
            task=task,
        )
    return value


def _as_str(value: Any, location: str, *, task: Optional[str] = None) -> str:
    if not isinstance(value, str):
        raise ConfigError(
            "expected a string, got %s" % type(value).__name__,
            location=location,
            task=task,
        )
    return value


def _as_str_list(
    value: Any, location: str, *, task: Optional[str] = None
) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(
            "expected an array of strings, got %s" % type(value).__name__,
            location=location,
            task=task,
        )
    out: List[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ConfigError(
                "entry %d is not a string" % index,
                location="%s[%d]" % (location, index),
                task=task,
            )
        if item == "":
            raise ConfigError(
                "entries must not be empty",
                location="%s[%d]" % (location, index),
                task=task,
            )
        out.append(item)
    return tuple(out)


def _as_bool(value: Any, location: str, *, task: Optional[str] = None) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(
            "expected a boolean, got %s" % type(value).__name__,
            location=location,
            task=task,
        )
    return value


def _as_int(
    value: Any,
    location: str,
    *,
    minimum: Optional[int] = None,
    task: Optional[str] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "expected an integer, got %s" % type(value).__name__,
            location=location,
            task=task,
        )
    if minimum is not None and value < minimum:
        raise ConfigError(
            "must be >= %d, got %d" % (minimum, value),
            location=location,
            task=task,
        )
    return value


def _as_number(
    value: Any,
    location: str,
    *,
    minimum: Optional[float] = None,
    exclusive_minimum: Optional[float] = None,
    task: Optional[str] = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "expected a number, got %s" % type(value).__name__,
            location=location,
            task=task,
        )
    result = float(value)
    if minimum is not None and result < minimum:
        raise ConfigError(
            "must be >= %s, got %s" % (minimum, result),
            location=location,
            task=task,
        )
    if exclusive_minimum is not None and result <= exclusive_minimum:
        raise ConfigError(
            "must be > %s, got %s" % (exclusive_minimum, result),
            location=location,
            task=task,
        )
    return result


def _validate_task_id(task_id: str, location: str) -> None:
    if not task_id:
        raise ConfigError("task identifier must not be empty", location=location)
    bad = set(task_id) - _VALID_TASK_ID
    if bad:
        raise ConfigError(
            "task identifier contains invalid character(s): %s"
            % ", ".join(sorted(repr(c) for c in bad)),
            location=location,
        )


def _ensure_relative_within_root(
    rel: str, root: Path, location: str, *, task: Optional[str] = None
) -> None:
    """Reject absolute paths and ``..`` escapes outside the workspace root."""
    candidate = Path(rel)
    if candidate.is_absolute():
        raise ConfigError(
            "path must be relative to the project root, got an absolute path: %s" % rel,
            location=location,
            task=task,
        )
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ConfigError(
            "path escapes the project workspace: %s" % rel,
            location=location,
            task=task,
        ) from None


def _build_project(raw: Mapping[str, Any], root: Path) -> ProjectConfig:
    project = _require_table(raw.get("project", {}), "project")
    _reject_unknown(project, _PROJECT_KEYS, "project")
    name = _as_str(project.get("name", root.name), "project.name")
    version = project.get("version", DEFAULT_CONFIG_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ConfigError(
            "expected an integer, got %s" % type(version).__name__,
            location="project.version",
        )
    if version not in SUPPORTED_CONFIG_VERSIONS:
        raise ConfigVersionError(
            "unsupported configuration version %r; supported versions: %s"
            % (version, ", ".join(str(v) for v in SUPPORTED_CONFIG_VERSIONS)),
            location="project.version",
        )
    return ProjectConfig(name=name, version=version, root=root, config_path=Path())


def _build_execution(raw: Mapping[str, Any]) -> ExecutionConfig:
    table = _require_table(raw.get("execution", {}), "execution")
    _reject_unknown(table, _EXECUTION_KEYS, "execution")
    max_workers = _as_int(
        table.get("max_workers", 1), "execution.max_workers", minimum=1
    )
    if max_workers > MAX_WORKERS_LIMIT:
        raise ConfigError(
            "max_workers must be <= %d, got %d" % (MAX_WORKERS_LIMIT, max_workers),
            location="execution.max_workers",
        )
    default_timeout = table.get("default_timeout_seconds")
    if default_timeout is not None:
        default_timeout = _as_number(
            default_timeout,
            "execution.default_timeout_seconds",
            exclusive_minimum=0.0,
        )
    fail_fast = _as_bool(table.get("fail_fast", False), "execution.fail_fast")
    return ExecutionConfig(
        max_workers=max_workers,
        default_timeout_seconds=default_timeout,
        fail_fast=fail_fast,
    )


def _build_cache(raw: Mapping[str, Any]) -> CacheConfig:
    table = _require_table(raw.get("cache", {}), "cache")
    _reject_unknown(table, _CACHE_KEYS, "cache")
    enabled = _as_bool(table.get("enabled", True), "cache.enabled")
    relevant_raw = table.get("relevant_env")
    if relevant_raw is None:
        relevant_env = DEFAULT_RELEVANT_ENV
    else:
        relevant_env = _as_str_list(relevant_raw, "cache.relevant_env")
    # 0 means "no limit"; an omitted key keeps the default bound.
    max_bytes_raw = table.get("max_bytes", 1_073_741_824)
    max_bytes = (
        None
        if max_bytes_raw == 0
        else _as_int(max_bytes_raw, "cache.max_bytes", minimum=1)
    )
    max_entries_raw = table.get("max_entries", 1000)
    max_entries = (
        None
        if max_entries_raw == 0
        else _as_int(max_entries_raw, "cache.max_entries", minimum=1)
    )
    return CacheConfig(
        enabled=enabled,
        relevant_env=tuple(relevant_env),
        max_bytes=max_bytes,
        max_entries=max_entries,
    )


def _build_history(raw: Mapping[str, Any]) -> HistoryConfig:
    table = _require_table(raw.get("history", {}), "history")
    _reject_unknown(table, _HISTORY_KEYS, "history")
    enabled = _as_bool(table.get("enabled", True), "history.enabled")
    max_runs = _as_int(table.get("max_runs", 500), "history.max_runs", minimum=1)
    return HistoryConfig(enabled=enabled, max_runs=max_runs)


def _build_notifications(raw: Mapping[str, Any]) -> NotificationsConfig:
    table = _require_table(raw.get("notifications", {}), "notifications")
    _reject_unknown(table, _NOTIFICATIONS_KEYS, "notifications")
    enabled = _as_bool(table.get("enabled", False), "notifications.enabled")
    url = _as_str(table.get("url", ""), "notifications.url")
    if enabled and not url:
        raise ConfigError(
            "notifications.url is required when notifications are enabled",
            location="notifications.url",
        )
    timeout = _as_number(
        table.get("timeout_seconds", 5.0),
        "notifications.timeout_seconds",
        exclusive_minimum=0.0,
    )
    max_attempts = _as_int(
        table.get("max_attempts", 2),
        "notifications.max_attempts",
        minimum=1,
    )
    on = _as_str_list(table.get("on", ["failure"]), "notifications.on")
    allowed_events = {"start", "success", "failure"}
    bad = [event for event in on if event not in allowed_events]
    if bad:
        raise ConfigError(
            "unknown notification event(s): %s" % ", ".join(bad),
            location="notifications.on",
        )
    return NotificationsConfig(
        enabled=enabled,
        url=url,
        timeout_seconds=timeout,
        max_attempts=max_attempts,
        on=tuple(on),
    )


def _build_retry(
    raw_value: Any, legacy_retries: Any, task: str, location: str
) -> RetryPolicy:
    if raw_value is None:
        if legacy_retries is None:
            return RetryPolicy()
        attempts = _as_int(legacy_retries, location, minimum=0, task=task)
        # ``retries`` counts retries after the first attempt.
        return RetryPolicy(max_attempts=attempts + 1)

    table = _require_table(raw_value, location, task=task)
    _reject_unknown(table, _RETRY_KEYS, location, task=task)
    max_attempts = _as_int(
        table.get("max_attempts", 1),
        "%s.max_attempts" % location,
        minimum=1,
        task=task,
    )
    delay = _as_number(
        table.get("delay_seconds", 0.0),
        "%s.delay_seconds" % location,
        minimum=0.0,
        task=task,
    )
    backoff = _as_bool(table.get("backoff", False), "%s.backoff" % location, task=task)
    max_delay = _as_number(
        table.get("max_delay_seconds", 60.0),
        "%s.max_delay_seconds" % location,
        minimum=0.0,
        task=task,
    )
    codes_raw = table.get("retry_on_exit_codes")
    codes: Optional[Tuple[int, ...]] = None
    if codes_raw is not None:
        if not isinstance(codes_raw, list):
            raise ConfigError(
                "expected an array of integers",
                location="%s.retry_on_exit_codes" % location,
                task=task,
            )
        codes_list: List[int] = []
        for index, code in enumerate(codes_raw):
            if isinstance(code, bool) or not isinstance(code, int):
                raise ConfigError(
                    "entry %d is not an integer" % index,
                    location="%s.retry_on_exit_codes[%d]" % (location, index),
                    task=task,
                )
            codes_list.append(code)
        codes = tuple(codes_list)
    return RetryPolicy(
        max_attempts=max_attempts,
        delay_seconds=delay,
        backoff=backoff,
        max_delay_seconds=max_delay,
        retry_on_exit_codes=codes,
    )


def _build_task(task_id: str, raw: Any, root: Path) -> TaskConfig:
    location = "tasks.%s" % task_id
    _validate_task_id(task_id, location)
    table = _require_table(raw, location, task=task_id)
    _reject_unknown(table, _TASK_KEYS, location, task=task_id)

    command = _as_str_list(table.get("command"), "%s.command" % location, task=task_id)
    if not command:
        raise ConfigError(
            "command must not be empty",
            location="%s.command" % location,
            task=task_id,
        )

    shell = _as_bool(table.get("shell", False), "%s.shell" % location, task=task_id)
    if shell and len(command) != 1:
        raise ConfigError(
            "when shell = true, command must be a single string",
            location="%s.command" % location,
            task=task_id,
        )

    depends_on = _as_str_list(
        table.get("depends_on", []), "%s.depends_on" % location, task=task_id
    )
    if task_id in depends_on:
        raise ConfigError(
            "task must not depend on itself",
            location="%s.depends_on" % location,
            task=task_id,
        )
    if len(set(depends_on)) != len(depends_on):
        raise ConfigError(
            "duplicate entries in depends_on",
            location="%s.depends_on" % location,
            task=task_id,
        )

    inputs = _as_str_list(table.get("inputs", []), "%s.inputs" % location, task=task_id)
    for index, pattern in enumerate(inputs):
        _ensure_relative_within_root(
            pattern,
            root,
            "%s.inputs[%d]" % (location, index),
            task=task_id,
        )

    outputs = _as_str_list(
        table.get("outputs", []), "%s.outputs" % location, task=task_id
    )
    for index, out in enumerate(outputs):
        _ensure_relative_within_root(
            out,
            root,
            "%s.outputs[%d]" % (location, index),
            task=task_id,
        )

    cwd = table.get("cwd")
    if cwd is not None:
        cwd = _as_str(cwd, "%s.cwd" % location, task=task_id)
        _ensure_relative_within_root(cwd, root, "%s.cwd" % location, task=task_id)

    env_raw = table.get("env", {})
    env = _require_table(env_raw, "%s.env" % location, task=task_id)
    env_out: Dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(key, str) or not key:
            raise ConfigError(
                "environment variable names must be non-empty strings",
                location="%s.env" % location,
                task=task_id,
            )
        if not isinstance(value, str):
            raise ConfigError(
                "value for env var %r must be a string" % key,
                location="%s.env.%s" % (location, key),
                task=task_id,
            )
        env_out[key] = value

    inherit_env = _as_bool(
        table.get("inherit_env", True),
        "%s.inherit_env" % location,
        task=task_id,
    )

    timeout = table.get("timeout_seconds")
    if timeout is not None:
        timeout = _as_number(
            timeout,
            "%s.timeout_seconds" % location,
            exclusive_minimum=0.0,
            task=task_id,
        )

    retry = _build_retry(
        table.get("retry"), table.get("retries"), task_id, "%s.retry" % location
    )

    max_output = table.get("max_output_bytes")
    if max_output is not None:
        max_output = _as_int(
            max_output,
            "%s.max_output_bytes" % location,
            minimum=1,
            task=task_id,
        )

    cache = _as_bool(table.get("cache", True), "%s.cache" % location, task=task_id)
    description = _as_str(
        table.get("description", ""), "%s.description" % location, task=task_id
    )

    return TaskConfig(
        id=task_id,
        command=command,
        depends_on=depends_on,
        inputs=inputs,
        outputs=outputs,
        cache=cache,
        cwd=cwd,
        env=env_out,
        inherit_env=inherit_env,
        timeout_seconds=timeout,
        retry=retry,
        shell=shell,
        description=description,
        resources=ResourceLimits(max_output_bytes=max_output),
    )


def build_workflow(
    raw: Mapping[str, Any], root: Path, config_path: Path
) -> WorkflowConfig:
    """Validate ``raw`` and produce an immutable :class:`WorkflowConfig`."""
    _reject_unknown(raw, _TOP_LEVEL_KEYS, "<root>")

    project = _build_project(raw, root)
    project = ProjectConfig(
        name=project.name,
        version=project.version,
        root=root,
        config_path=config_path,
    )
    execution = _build_execution(raw)
    cache = _build_cache(raw)
    history = _build_history(raw)
    notifications = _build_notifications(raw)

    tasks_raw = _require_table(raw.get("tasks", {}), "tasks")
    if not tasks_raw:
        raise ConfigError("no tasks defined", location="tasks")
    tasks: Dict[str, TaskConfig] = {}
    for task_id, task_raw in tasks_raw.items():
        if task_id in tasks:
            raise ConfigError(
                "duplicate task identifier", location="tasks.%s" % task_id
            )
        tasks[task_id] = _build_task(task_id, task_raw, root)

    return WorkflowConfig(
        project=project,
        execution=execution,
        tasks=tasks,
        cache=cache,
        history=history,
        notifications=notifications,
    )


def normalize_root(raw_root: Optional[str], base: Path) -> Path:
    """Resolve the workspace root from CLI/config, constrained to ``base``."""
    if raw_root is None:
        return base.resolve()
    candidate = Path(raw_root)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        raise ConfigError(
            "project root must be inside the working directory: %s" % raw_root
        ) from None
    return resolved


def environment_name() -> str:
    """Return a platform description for diagnostics (never the full env)."""
    return os.name
