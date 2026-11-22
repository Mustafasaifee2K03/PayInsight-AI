"""Application state database (users, auth sessions, auth audit log, analysis history, settings).

Kept separate from the payments database so that analytical connections can be
strictly read-only and so reseeding never touches users or history.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator

from ..config import get_settings

APP_DDL = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('ADMIN','ANALYST','VIEWER')),
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_history (
    analysis_id TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(user_id),
    question    TEXT NOT NULL,
    status      TEXT NOT NULL,
    intent      TEXT,
    scenario_id TEXT,
    created_at  TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_user ON analysis_history(user_id, created_at);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Versioned, idempotent migrations applied in order. PRAGMA user_version records progress.
MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        # account state for lockout / deactivation / auditing
        "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE users ADD COLUMN created_at TEXT",
        "ALTER TABLE users ADD COLUMN last_login_at TEXT",
        "ALTER TABLE users ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN locked_until TEXT",
        "ALTER TABLE users ADD COLUMN password_changed_at TEXT",
        "UPDATE users SET created_at = COALESCE(created_at, strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))",
        # the old opaque-token table is superseded by refresh-token sessions
        "DROP TABLE IF EXISTS sessions",
        """CREATE TABLE IF NOT EXISTS auth_sessions (
            session_id            TEXT PRIMARY KEY,
            user_id               INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            refresh_token_hash    TEXT NOT NULL UNIQUE,
            previous_refresh_hash TEXT,
            rotation_count        INTEGER NOT NULL DEFAULT 0,
            created_at            TEXT NOT NULL,
            last_used_at          TEXT NOT NULL,
            expires_at            TEXT NOT NULL,
            revoked_at            TEXT,
            revoke_reason         TEXT,
            user_agent            TEXT,
            ip_address            TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, revoked_at)",
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_prev ON auth_sessions(previous_refresh_hash)",
        """CREATE TABLE IF NOT EXISTS auth_audit_log (
            event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            outcome    TEXT NOT NULL CHECK (outcome IN ('SUCCESS','FAILURE')),
            user_id    INTEGER,
            email      TEXT,
            session_id TEXT,
            ip_address TEXT,
            detail     TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_audit_time ON auth_audit_log(occurred_at)",
    ]),
    # Hardening iteration 3: rotation time is tracked separately from "last used". The reuse-detection grace
    # window was measured from last_used_at, which every API call refreshes, so a stolen refresh token
    # replayed shortly after any API call was treated as a benign multi-tab race instead of theft.
    (2, [
        "ALTER TABLE auth_sessions ADD COLUMN rotated_at TEXT",
    ]),
    # Hardening iteration 10: EXPLAIN QUERY PLAN showed full scans on hot paths (session purge on every
    # login; audit filter by event type). Covering index for per-user active-session counts.
    (3, [
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_active ON auth_sessions(user_id, revoked_at, expires_at)",
        "DROP INDEX IF EXISTS idx_auth_sessions_user",
        "CREATE INDEX IF NOT EXISTS idx_audit_type ON auth_audit_log(event_type, event_id)",
    ]),
]

_lock = threading.Lock()


class FairWriteGate:
    """Re-entrant FIFO (ticket) lock serialising app.db write transactions inside this process.

    Hardening iteration 10: under 32 concurrent sign-ins SQLite's busy handler (sleep-and-retry polling,
    no queue) let unlucky writers starve: p50 32 ms but p95 1.6 s and max 3.3 s. Queueing writers in
    arrival order means each one waits only for the work ahead of it. Readers are never gated (WAL).
    Across *processes* SQLite's own lock still applies; a multi-node deployment would move app state
    to a server database (see docs/HARDENING_REPORT.md, scaling section)."""

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._queue: deque[threading.Event] = deque()   # waiters in arrival order; each is woken individually
        self._owner: int | None = None
        self._depth = 0

    def acquire(self) -> None:
        me = threading.get_ident()
        with self._mutex:
            if self._owner == me:
                self._depth += 1
                return
            if self._owner is None and not self._queue:
                self._owner, self._depth = me, 1
                return
            ev = threading.Event()
            self._queue.append(ev)
        ev.wait()  # ownership is handed over directly by release(): wake exactly one thread, no stampede
        with self._mutex:
            self._owner, self._depth = me, 1

    def release(self) -> None:
        with self._mutex:
            self._depth -= 1
            if self._depth:
                return
            self._owner = None
            if self._queue:
                self._owner = -1          # reserved for the woken waiter (prevents barging)
                self._queue.popleft().set()


write_gate = FairWriteGate()


def _gate_enabled() -> bool:
    return get_settings().app_db_write_gate
_WRITE_SQL = re.compile(r"^\s*(insert|update|delete|replace|create|drop|alter)\b", re.IGNORECASE)


class GatedConnection(sqlite3.Connection):
    """sqlite3 connection that takes ``write_gate`` when a write transaction starts and releases it on
    commit / rollback / close. Python's sqlite3 opens the transaction implicitly at the first DML."""

    _gated = False

    def _enter(self, sql: str) -> bool:
        if not self._gated and not self.in_transaction and _gate_enabled() and _WRITE_SQL.match(sql):
            write_gate.acquire()
            self._gated = True
            return True
        return False

    def _leave(self) -> None:
        if self._gated:
            self._gated = False
            write_gate.release()

    def execute(self, sql, parameters=(), /):  # type: ignore[override]
        took = self._enter(sql)
        try:
            return super().execute(sql, parameters)
        except BaseException:
            if took and not self.in_transaction:
                self._leave()
            raise

    def commit(self) -> None:  # type: ignore[override]
        try:
            super().commit()
        finally:
            self._leave()

    def rollback(self) -> None:  # type: ignore[override]
        try:
            super().rollback()
        finally:
            self._leave()

    def close(self) -> None:  # type: ignore[override]
        try:
            super().close()
        finally:
            self._leave()


@contextmanager
def app_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_settings().app_db_path, timeout=10, check_same_thread=False, factory=GatedConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _apply_migrations(c: sqlite3.Connection) -> None:
    current = c.execute("PRAGMA user_version").fetchone()[0]
    for version, statements in MIGRATIONS:
        if version <= current:
            continue
        for stmt in statements:
            try:
                c.execute(stmt)
            except sqlite3.OperationalError as exc:  # column already exists on a partially migrated DB
                if "duplicate column" not in str(exc):
                    raise
        c.execute(f"PRAGMA user_version = {int(version)}")
        c.commit()


def init_app_store() -> None:
    with _lock, app_conn() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(APP_DDL)
        _apply_migrations(c)


def schema_version() -> int:
    with app_conn() as c:
        return c.execute("PRAGMA user_version").fetchone()[0]


def get_setting(key: str, default: str | None = None) -> str | None:
    with app_conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with app_conn() as c:
        c.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def save_history(analysis_id: str, user_id: int, question: str, status: str, intent: str | None,
                 scenario_id: str | None, created_at: str, result: dict[str, Any]) -> None:
    with app_conn() as c:
        c.execute(
            "INSERT INTO analysis_history VALUES (?,?,?,?,?,?,?,?)",
            (analysis_id, user_id, question, status, intent, scenario_id, created_at, json.dumps(result, default=str)),
        )
        # keep the most recent 200 analyses per user
        c.execute(
            "DELETE FROM analysis_history WHERE user_id = ? AND analysis_id NOT IN "
            "(SELECT analysis_id FROM analysis_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 200)",
            (user_id, user_id),
        )


def list_history(user_id: int, limit: int = 50) -> list[dict]:
    with app_conn() as c:
        rows = c.execute(
            "SELECT analysis_id, question, status, intent, scenario_id, created_at FROM analysis_history "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_history_item(analysis_id: str) -> dict | None:
    with app_conn() as c:
        row = c.execute("SELECT * FROM analysis_history WHERE analysis_id = ?", (analysis_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["result"] = json.loads(d.pop("result_json"))
        return d
