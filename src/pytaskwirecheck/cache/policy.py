"""Cache policy decisions and construction helpers.

Policy is deliberately simple: the global config may disable the cache, the
CLI may disable it for a single run (``--no-cache``), and individual tasks may
opt out. A task with no declared inputs or outputs is never cached because its
side effects are unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from pytaskwirecheck.cache.remote import RemoteCache
from pytaskwirecheck.cache.store import CacheStore
from pytaskwirecheck.config.schema import TaskConfig, WorkflowConfig


@dataclass(frozen=True)
class CacheDecision:
    use_cache: bool
    reason: str


def decide(
    task: TaskConfig, *, global_enabled: bool, cli_disabled: bool
) -> CacheDecision:
    """Decide whether cache reads/writes apply to ``task`` in this run."""
    if cli_disabled:
        return CacheDecision(False, "disabled for this run (--no-cache)")
    if not global_enabled:
        return CacheDecision(False, "disabled in configuration")
    if not task.cache:
        return CacheDecision(False, "opted out by task")
    if not task.cache_eligible:
        return CacheDecision(False, "no declared inputs or outputs")
    return CacheDecision(True, "eligible")


def build_store(
    config: WorkflowConfig,
    *,
    base_env: Optional[Mapping[str, str]] = None,
) -> CacheStore:
    """Construct a :class:`CacheStore` for ``config``."""
    remote = None
    if config.cache.remote_url:
        remote = RemoteCache(
            config.cache.remote_url,
            token=config.cache.remote_token,
            timeout_seconds=config.cache.remote_timeout_seconds,
        )
    return CacheStore(
        config.project.root,
        base_env=base_env,
        relevant_env=config.cache.relevant_env,
        max_bytes=config.cache.max_bytes,
        max_entries=config.cache.max_entries,
        remote=remote,
    )
