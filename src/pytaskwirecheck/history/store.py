"""Local execution history backed by SQLite.

The history is a convenience, never a dependency: a write failure is surfaced
to the caller but must never change a run's outcome. The database lives under
``<root>/.pytaskwirecheck/history.db`` and uses WAL mode for safe concurrent readers.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional

from pytaskwirecheck.config.loader import state_dir
from pytaskwirecheck.diagnostics.errors import HistoryError
from pytaskwirecheck.engine.scheduler import RunResult

SCHEMA_VERSION = 1


class HistoryStore:
    """A minimal, local execution-history store."""

    def __init__(self, root: Path, *, max_runs: int = 500) -> None:
        self._root = root.resolve()
        self._path = state_dir(self._root) / "history.db"
        self._max_runs = max_runs
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path), timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._create_schema(conn)
            self._conn = conn
        except sqlite3.Error as exc:
            raise HistoryError("cannot open history database: %s" % exc) from exc
        return conn

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                project TEXT,
                config_version INTEGER,
                started_at REAL,
                ended_at REAL,
                duration_seconds REAL,
                succeeded INTEGER,
                cancelled INTEGER,
                summary_json TEXT
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()

    def record_run(
        self,
        result: RunResult,
        *,
        project: str,
        config_version: int,
    ) -> None:
        """Persist a run summary. Raises :class:`HistoryError` on failure."""
        summary = result.summary()
        ended_at = time.time()
        started_at = ended_at - result.duration_seconds
        with self._lock:
            try:
                conn = self._connect()
                conn.execute(
                    """
                    INSERT OR REPLACE INTO runs
                    (run_id, project, config_version, started_at, ended_at,
                     duration_seconds, succeeded, cancelled, summary_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.run_id,
                        project,
                        config_version,
                        started_at,
                        ended_at,
                        result.duration_seconds,
                        1 if result.succeeded else 0,
                        1 if result.cancelled else 0,
                        json.dumps(summary, separators=(",", ":")),
                    ),
                )
                conn.commit()
                self._prune(conn)
            except sqlite3.Error as exc:
                raise HistoryError("cannot record run: %s" % exc) from exc

    def _prune(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            DELETE FROM runs WHERE run_id NOT IN (
                SELECT run_id FROM runs ORDER BY ended_at DESC LIMIT ?
            )
            """,
            (self._max_runs,),
        )
        conn.commit()

    def recent(self, limit: int = 20) -> List[dict]:
        with self._lock:
            try:
                conn = self._connect()
                rows = conn.execute(
                    """
                    SELECT run_id, project, started_at, ended_at,
                           duration_seconds, succeeded, cancelled, summary_json
                    FROM runs ORDER BY ended_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            except sqlite3.Error as exc:
                raise HistoryError("cannot read history: %s" % exc) from exc
        results = []
        for row in rows:
            results.append(
                {
                    "run_id": row[0],
                    "project": row[1],
                    "started_at": row[2],
                    "ended_at": row[3],
                    "duration_seconds": row[4],
                    "succeeded": bool(row[5]),
                    "cancelled": bool(row[6]),
                    "summary": json.loads(row[7]) if row[7] else {},
                }
            )
        return results

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None
