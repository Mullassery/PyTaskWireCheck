"""Immutable data model for a validated PyTaskWireCheck workflow configuration.

These dataclasses are the single source of truth for configuration once it has
been parsed and validated. They contain no I/O and no behaviour beyond simple
derived queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

#: The configuration schema versions PyTaskWireCheck understands.
SUPPORTED_CONFIG_VERSIONS: Tuple[int, ...] = (1,)

#: The version written by ``pytaskwirecheck init`` and accepted by this release.
DEFAULT_CONFIG_VERSION = 1

#: Maximum number of workers we will ever create in a single run.
MAX_WORKERS_LIMIT = 256

#: Environment variable names that affect task results by default. Tasks may
#: add their own via the ``env`` table. See :mod:`pytaskwirecheck.cache.fingerprint`.
DEFAULT_RELEVANT_ENV: Tuple[str, ...] = (
    "PATH",
    "PYTHONPATH",
    "PYTHONHASHSEED",
    "LANG",
    "LC_ALL",
    "TZ",
)


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry behaviour for a task.

    ``max_attempts`` counts the initial attempt, so ``1`` means "no retries".
    """

    max_attempts: int = 1
    delay_seconds: float = 0.0
    backoff: bool = False
    max_delay_seconds: float = 60.0
    retry_on_exit_codes: Optional[Tuple[int, ...]] = None

    @property
    def enabled(self) -> bool:
        return self.max_attempts > 1

    def delay_for_attempt(self, attempt: int) -> float:
        """Return the delay (seconds) before ``attempt`` (1-based).

        ``attempt`` is the upcoming attempt number; the delay before attempt 1
        is always zero.
        """
        if attempt <= 1:
            return 0.0
        if not self.backoff:
            return self.delay_seconds
        delay = self.delay_seconds * (2 ** (attempt - 2))
        return min(delay, self.max_delay_seconds)

    def should_retry_exit_code(self, code: int) -> bool:
        if self.retry_on_exit_codes is None:
            return code != 0
        return code in self.retry_on_exit_codes


@dataclass(frozen=True)
class ResourceLimits:
    """Optional, best-effort resource limits for a task process."""

    max_output_bytes: Optional[int] = None


@dataclass(frozen=True)
class TaskConfig:
    """A single task definition from ``pytaskwirecheck.toml``."""

    id: str
    command: Tuple[str, ...]
    depends_on: Tuple[str, ...] = ()
    inputs: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()
    cache: bool = True
    cwd: Optional[str] = None
    env: Mapping[str, str] = field(default_factory=dict)
    inherit_env: bool = True
    timeout_seconds: Optional[float] = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    shell: bool = False
    description: str = ""
    resources: ResourceLimits = field(default_factory=ResourceLimits)

    @property
    def cache_eligible(self) -> bool:
        """Whether the task may produce/consume cache entries.

        A task must declare at least one output to be cacheable. An
        input-only task has nothing to store, so marking it eligible would
        advertise a cache entry that :meth:`CacheStore.store` never writes
        (PyTaskWireCheck cannot know what result to restore).
        """
        if not self.cache:
            return False
        return bool(self.outputs)


@dataclass(frozen=True)
class ExecutionConfig:
    """Global execution settings."""

    max_workers: int = 1
    default_timeout_seconds: Optional[float] = None
    fail_fast: bool = False


@dataclass(frozen=True)
class CacheConfig:
    """Global cache settings."""

    enabled: bool = True
    relevant_env: Tuple[str, ...] = DEFAULT_RELEVANT_ENV
    max_bytes: Optional[int] = 1_073_741_824
    max_entries: Optional[int] = 1000
    remote_url: str = ""
    remote_token: str = ""
    remote_timeout_seconds: float = 10.0


@dataclass(frozen=True)
class NotificationsConfig:
    """Optional webhook notification settings (disabled by default)."""

    enabled: bool = False
    url: str = ""
    timeout_seconds: float = 5.0
    max_attempts: int = 2
    on: Tuple[str, ...] = ("failure",)


@dataclass(frozen=True)
class HistoryConfig:
    """Local execution history settings."""

    enabled: bool = True
    max_runs: int = 500


@dataclass(frozen=True)
class ProjectConfig:
    """Project-level metadata and the resolved workspace root."""

    name: str
    version: int
    root: Path
    config_path: Path


@dataclass(frozen=True)
class WorkflowConfig:
    """A fully validated workflow: project metadata plus its tasks."""

    project: ProjectConfig
    execution: ExecutionConfig
    tasks: Mapping[str, TaskConfig]
    cache: CacheConfig = field(default_factory=CacheConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)

    def task_ids(self) -> List[str]:
        return list(self.tasks.keys())

    def get(self, task_id: str) -> TaskConfig:
        return self.tasks[task_id]
