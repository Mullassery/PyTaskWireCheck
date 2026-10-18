"""Local content-addressed cache storage.

Layout (under ``<root>/.pytaskwirecheck/cache``)::

    entries/<key>/meta.json         # fingerprint + artifact manifest
    entries/<key>/artifacts/...     # stored copies of declared outputs
    stage/                          # staging area for atomic commits
    locks/                          # short-lived commit locks

Correctness rules:

* Only successful executions commit entries.
* Commits are atomic: artifacts are staged, then the directory is renamed.
* Restores verify artifact integrity first; a corrupt or partial entry is a
  miss, never a false success.
* Restoration is confined to the workspace root.
* The cache is bounded: after each commit, least-recently-used entries are
  evicted until ``max_entries``/``max_bytes`` hold (see :meth:`CacheStore.evict`).
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pytaskwirecheck import __version__
from pytaskwirecheck.cache.fingerprint import (
    CACHE_SCHEMA_VERSION,
    DEFAULT_RELEVANT_ENV,
    Fingerprint,
    compute_fingerprint,
    hash_file,
)
from pytaskwirecheck.config.loader import state_dir
from pytaskwirecheck.config.schema import TaskConfig
from pytaskwirecheck.diagnostics.errors import CacheError

_LOCK_TIMEOUT = 10.0
_LOCK_POLL = 0.05

#: Default bound on total cache size (1 GiB) before least-recently-used
#: entries are evicted. ``None`` disables the byte bound.
DEFAULT_MAX_BYTES: Optional[int] = 1_073_741_824
#: Default bound on the number of entries before least-recently-used entries
#: are evicted. ``None`` disables the entry-count bound.
DEFAULT_MAX_ENTRIES: Optional[int] = 1000


class _CommitLock:
    """A best-effort cross-process lock for committing a single cache key."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: Optional[int] = None

    def __enter__(self) -> "_CommitLock":
        deadline = time.monotonic() + _LOCK_TIMEOUT
        self._path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._fd = os.open(
                    str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    # Stale lock; break it and proceed.
                    try:
                        os.unlink(self._path)
                    except OSError:
                        pass
                    continue
                time.sleep(_LOCK_POLL)

    def __exit__(self, *exc: object) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            os.unlink(self._path)
        except OSError:
            pass


class CacheStore:
    """A local, self-contained content-addressed cache."""

    def __init__(
        self,
        root: Path,
        *,
        base_env: Optional[Mapping[str, str]] = None,
        relevant_env: Sequence[str] = DEFAULT_RELEVANT_ENV,
        max_bytes: Optional[int] = DEFAULT_MAX_BYTES,
        max_entries: Optional[int] = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._root = root.resolve()
        self._base = state_dir(self._root) / "cache"
        self._entries = self._base / "entries"
        self._stage = self._base / "stage"
        self._locks = self._base / "locks"
        self._base_env = base_env
        self._relevant_env = tuple(relevant_env)
        self._max_bytes = max_bytes
        self._max_entries = max_entries

    @property
    def location(self) -> Path:
        return self._base

    def fingerprint(
        self, task: TaskConfig, dependency_keys: Mapping[str, Optional[str]]
    ) -> Fingerprint:
        return compute_fingerprint(
            task,
            self._root,
            dependency_keys,
            base_env=self._base_env,
            relevant_env=self._relevant_env,
        )

    # -- lookup / restore ---------------------------------------------------

    def try_restore(
        self, task: TaskConfig, dependency_keys: Mapping[str, Optional[str]]
    ) -> Optional[str]:
        if not task.cache_eligible:
            return None
        fp = self.fingerprint(task, dependency_keys)
        entry = self._entries / fp.key
        meta_path = entry / "meta.json"
        if not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._discard(fp.key)
            return None
        if meta.get("schema") != CACHE_SCHEMA_VERSION:
            self._discard(fp.key)
            return None

        artifacts = meta.get("artifacts", [])
        if not self._verify_artifacts(entry, artifacts):
            self._discard(fp.key)
            return None
        if not self._restore_artifacts(entry, artifacts):
            return None
        self._touch(entry)
        return fp.key

    def _touch(self, entry: Path) -> None:
        """Mark an entry as most-recently-used by bumping its directory mtime.

        The entry directory's mtime (not the artifact files', which are what
        integrity checks read) is the LRU clock used by :meth:`evict`.
        """
        try:
            os.utime(entry, None)
        except OSError:
            pass

    def _verify_artifacts(self, entry: Path, artifacts: List[dict]) -> bool:
        for artifact in artifacts:
            stored = entry / "artifacts" / artifact["path"]
            if not stored.is_file():
                return False
            try:
                if stored.stat().st_size != artifact.get("size"):
                    return False
                if hash_file(stored) != artifact.get("sha256"):
                    return False
            except OSError:
                return False
        return True

    def _safe_destination(self, rel: str) -> Optional[Path]:
        if os.path.isabs(rel):
            return None
        destination = (self._root / rel).resolve()
        try:
            destination.relative_to(self._root)
        except ValueError:
            return None
        return destination

    def _restore_artifacts(self, entry: Path, artifacts: List[dict]) -> bool:
        for artifact in artifacts:
            destination = self._safe_destination(artifact["path"])
            if destination is None:
                return False
            source = entry / "artifacts" / artifact["path"]
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            except OSError:
                return False
        return True

    # -- commit / store -----------------------------------------------------

    def store(
        self, task: TaskConfig, dependency_keys: Mapping[str, Optional[str]]
    ) -> Optional[str]:
        if not task.cache_eligible:
            return None
        collected, missing = self._collect_outputs(task)
        if not task.outputs:
            return None
        if missing:
            # Declared output absent: refuse to cache an incomplete result.
            return None

        fp = self.fingerprint(task, dependency_keys)
        stage_dir = self._stage / ("%s.%s" % (fp.key, uuid.uuid4().hex))
        artifacts_dir = stage_dir / "artifacts"
        artifacts: List[dict] = []
        try:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            for rel, source in collected:
                dest = artifacts_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
                artifacts.append(
                    {
                        "path": rel,
                        "sha256": hash_file(dest),
                        "size": dest.stat().st_size,
                    }
                )
            meta = {
                "schema": CACHE_SCHEMA_VERSION,
                "key": fp.key,
                "task_id": task.id,
                "created_at": time.time(),
                "pytaskwirecheck_version": __version__,
                "fingerprint": fp.payload,
                "artifacts": artifacts,
            }
            (stage_dir / "meta.json").write_text(
                json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8"
            )
            self._commit(fp.key, stage_dir)
        except OSError as exc:
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise CacheError("failed to store cache entry: %s" % exc) from exc
        self.evict(protect=fp.key)
        return fp.key

    def _collect_outputs(
        self, task: TaskConfig
    ) -> Tuple[List[Tuple[str, Path]], List[str]]:
        collected: Dict[str, Path] = {}
        missing: List[str] = []
        for pattern in task.outputs:
            matches = sorted(self._root.glob(pattern))
            matched_any = False
            for match in matches:
                if match.is_dir():
                    files = [f for f in _iter_files(match)]
                    if files:
                        matched_any = True
                else:
                    files = [match]
                    matched_any = True
                for file_path in files:
                    try:
                        rel = file_path.resolve().relative_to(self._root).as_posix()
                    except ValueError:
                        continue
                    collected[rel] = file_path
            if not matched_any:
                missing.append(pattern)
        return (
            [(rel, collected[rel]) for rel in sorted(collected)],
            missing,
        )

    def _commit(self, key: str, stage_dir: Path) -> None:
        target = self._entries / key
        lock = _CommitLock(self._locks / ("%s.lock" % key))
        with lock:
            self._entries.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            try:
                os.replace(str(stage_dir), str(target))
            except OSError:
                shutil.rmtree(stage_dir, ignore_errors=True)
                raise

    def _discard(self, key: str) -> None:
        shutil.rmtree(self._entries / key, ignore_errors=True)

    def evict(self, protect: Optional[str] = None) -> dict:
        """Evict least-recently-used entries until the configured bounds hold.

        Bounds are ``max_entries`` (entry count) and ``max_bytes`` (total size on
        disk), either of which may be ``None`` for "unbounded". Entries are
        ordered by their directory mtime, which :meth:`_touch` advances on every
        successful restore — so ``protect`` (the key just committed) is never
        evicted for being new, only if it alone exceeds a bound.

        Returns a summary dict ``{"removed_entries", "removed_bytes"}``.
        """
        if not self._entries.is_dir():
            return {"removed_entries": 0, "removed_bytes": 0}
        if self._max_entries is None and self._max_bytes is None:
            return {"removed_entries": 0, "removed_bytes": 0}

        candidates: List[Tuple[float, Path]] = []
        for child in self._entries.iterdir():
            if not child.is_dir() or child.name == protect:
                continue
            try:
                mtime = child.stat().st_mtime
            except OSError:
                mtime = 0.0
            candidates.append((mtime, child))
        candidates.sort(key=lambda item: item[0])

        total = sum(_dir_size(path) for _, path in candidates)
        if protect is not None:
            total += _dir_size(self._entries / protect)
        count = len(candidates) + (1 if protect is not None else 0)

        removed = 0
        freed = 0
        while candidates and (
            (self._max_entries is not None and count > self._max_entries)
            or (self._max_bytes is not None and total > self._max_bytes)
        ):
            _, path = candidates.pop(0)
            size = _dir_size(path)
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
            freed += size
            count -= 1
            total -= size
        return {"removed_entries": removed, "removed_bytes": freed}

    # -- inspection ---------------------------------------------------------

    def explain(
        self, task: TaskConfig, dependency_keys: Mapping[str, Optional[str]]
    ) -> dict:
        """Explain why a task would hit or miss the cache."""
        if not task.cache:
            return {"eligible": False, "reason": "caching disabled for task"}
        if not task.cache_eligible:
            return {
                "eligible": False,
                "reason": "task declares no outputs",
            }
        fp = self.fingerprint(task, dependency_keys)
        entry = self._entries / fp.key
        if not (entry / "meta.json").is_file():
            return {
                "eligible": True,
                "hit": False,
                "key": fp.key,
                "reason": "no cache entry for computed fingerprint",
                "inputs": [asdict(f) for f in fp.inputs],
                "missing_patterns": list(fp.missing_patterns),
                "env_names": list(fp.env_names),
            }
        meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
        valid = self._verify_artifacts(entry, meta.get("artifacts", []))
        return {
            "eligible": True,
            "hit": valid,
            "key": fp.key,
            "reason": "entry valid" if valid else "entry corrupted",
            "inputs": [asdict(f) for f in fp.inputs],
            "artifacts": meta.get("artifacts", []),
        }

    def status(self) -> dict:
        if not self._entries.is_dir():
            return {
                "location": str(self._base),
                "entries": 0,
                "size_bytes": 0,
                "corrupted": 0,
                "max_bytes": self._max_bytes,
                "max_entries": self._max_entries,
            }
        entries = 0
        corrupted = 0
        size = 0
        for child in sorted(self._entries.iterdir()):
            if not child.is_dir():
                continue
            entries += 1
            meta_path = child / "meta.json"
            if not meta_path.is_file():
                corrupted += 1
            else:
                try:
                    json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    corrupted += 1
            size += _dir_size(child)
        return {
            "location": str(self._base),
            "entries": entries,
            "size_bytes": size,
            "corrupted": corrupted,
            "max_bytes": self._max_bytes,
            "max_entries": self._max_entries,
        }

    def clean(self) -> dict:
        freed = _dir_size(self._base) if self._base.is_dir() else 0
        shutil.rmtree(self._base, ignore_errors=True)
        return {"removed_bytes": freed}


def _iter_files(base: Path):
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in sorted(filenames):
            candidate = Path(dirpath) / name
            if candidate.is_file() and not candidate.is_symlink():
                yield candidate


def _dir_size(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total
