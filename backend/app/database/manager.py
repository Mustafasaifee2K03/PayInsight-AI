"""Payments-database lifecycle: active profile, generation, read-only connections.

* One SQLite file per data profile (``data/payments_<profile>.db``).
* Analytical connections are opened with ``mode=ro`` **and** ``PRAGMA query_only``.
* A readers/writer lock prevents a reseed from swapping a file while queries run.
* ``generation`` is a monotonically increasing counter used to invalidate caches.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import get_settings
from .generator import PROFILES, GenerationResult, build_database


class ReadWriteLock:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False

    @contextmanager
    def read(self) -> Iterator[None]:
        with self._cond:
            while self._writer:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                self._cond.notify_all()

    @contextmanager
    def write(self) -> Iterator[None]:
        with self._cond:
            while self._writer or self._readers:
                self._cond.wait()
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()


def apply_heap_limit(limit_mb: int) -> int:
    """Set SQLite's process-wide hard heap limit; allocations beyond it fail with SQLITE_NOMEM
    (surfaced by Python as MemoryError) instead of exhausting the machine."""
    conn = sqlite3.connect(":memory:")
    try:
        return conn.execute(f"PRAGMA hard_heap_limit = {max(0, int(limit_mb)) * 1024 * 1024}").fetchone()[0]
    finally:
        conn.close()


class DatabaseManager:
    def __init__(self) -> None:
        self.settings = get_settings()
        apply_heap_limit(self.settings.sqlite_heap_limit_mb)
        self.lock = ReadWriteLock()
        self._profile = "baseline"
        self._path_override: Path | None = None
        self.generation = 0
        self._gen_lock = threading.Lock()

    # -- profile management -------------------------------------------------
    @property
    def profile(self) -> str:
        return self._profile

    @property
    def path(self) -> Path:
        return self._path_override or self.settings.payments_db_path(self._profile)

    def use_path(self, path: Path | str) -> None:
        """Point analytics at an explicit database file (benchmarks / tests)."""
        with self.lock.write():
            self._path_override = Path(path)
            self.generation += 1

    def ensure_profile(self, profile: str, *, rebuild: bool = False) -> GenerationResult | None:
        if profile not in PROFILES:
            raise ValueError(f"Unknown data profile {profile!r}")
        target = self.settings.payments_db_path(profile)
        if target.exists() and not rebuild:
            return None
        with self._gen_lock, self.lock.write():
            if target.exists() and not rebuild:
                return None
            s = self.settings
            result = build_database(target, profile, s.default_row_count, s.random_seed, s.data_start_date, s.data_days)
            self.generation += 1
            return result

    def activate(self, profile: str, *, rebuild: bool = False) -> GenerationResult | None:
        result = self.ensure_profile(profile, rebuild=rebuild)
        with self.lock.write():
            self._profile = profile
            self._path_override = None
            self.generation += 1
        return result

    # -- connections ---------------------------------------------------------
    def _connect_ro(self) -> sqlite3.Connection:
        uri = f"file:{self.path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=5)
        conn.execute("PRAGMA query_only = ON")
        return conn

    @contextmanager
    def readonly(self) -> Iterator[sqlite3.Connection]:
        """Read-only analytical connection held under the shared (reader) lock."""
        with self.lock.read():
            conn = self._connect_ro()
            try:
                yield conn
            finally:
                conn.close()


_manager: DatabaseManager | None = None


def get_db() -> DatabaseManager:
    global _manager
    if _manager is None:
        _manager = DatabaseManager()
    return _manager
