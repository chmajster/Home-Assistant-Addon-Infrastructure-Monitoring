from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Iterator


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._transaction_depth = 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, tuple(params))
            if self._transaction_depth == 0:
                self._conn.commit()
            return cursor

    def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self._conn.executemany(sql, params)
            if self._transaction_depth == 0:
                self._conn.commit()

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)
            if self._transaction_depth == 0:
                self._conn.commit()

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            outermost = self._transaction_depth == 0
            if outermost:
                self._conn.execute("BEGIN")
            self._transaction_depth += 1
            try:
                yield
                self._transaction_depth -= 1
                if outermost:
                    self._conn.commit()
            except Exception:
                self._transaction_depth -= 1
                if outermost:
                    self._conn.rollback()
                raise

    def diagnostics(self) -> dict[str, Any]:
        def count(table: str) -> int:
            row = self.fetchone(f"SELECT COUNT(*) AS count FROM {table}")
            return int(row["count"] if row else 0)

        checks_range = self.fetchone(
            "SELECT MIN(checked_at) AS oldest_check, MAX(checked_at) AS newest_check FROM monitor_checks"
        )
        wal_path = self.path.with_name(f"{self.path.name}-wal")
        return {
            "database_size_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "wal_size_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
            "monitor_count": count("monitors"),
            "group_count": count("monitor_groups"),
            "check_count": count("monitor_checks"),
            "event_count": count("events"),
            "snapshot_count": count("website_snapshots"),
            "incident_count": count("incidents"),
            "oldest_check": checks_range.get("oldest_check") if checks_range else None,
            "newest_check": checks_range.get("newest_check") if checks_range else None,
        }


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
