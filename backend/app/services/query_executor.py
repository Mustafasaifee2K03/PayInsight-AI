"""Validated, read-only, time-limited query execution with result caching."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ..config import get_settings
from ..core.errors import QueryExecutionError, QueryResourceError, QueryTimeoutError, SQLValidationError
from ..database.manager import get_db
from .sql_compiler import CompiledQuery
from .sql_validator import validate_sql

log = logging.getLogger("payinsight.query")

# SQLite authorizer action codes that analytical queries may perform.
_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, getattr(sqlite3, "SQLITE_RECURSIVE", 33)}
_DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}
MAX_CELL_CHARS = 10_000  # bounds the JSON payload: 500 sandbox rows x huge strings would otherwise be sent verbatim


def _cell(value: Any) -> Any:
    """Make a cell JSON-safe and bounded (BLOBs become hex; very long text is truncated)."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = "x'" + bytes(value).hex() + "'"
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + f"… [truncated {len(value) - MAX_CELL_CHARS} chars]"
    return value


def _authorizer(action, arg1, arg2, dbname, source):
    if action not in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in _DENIED_FUNCTIONS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


@dataclass
class QueryRun:
    purpose: str
    sql: str
    params: dict[str, Any]
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    row_count: int = 0
    truncated: bool = False
    cached: bool = False
    status: str = "success"
    tables: list[str] = field(default_factory=list)
    limit_applied: int | None = None

    def meta(self) -> dict:
        return {
            "purpose": self.purpose, "sql": self.sql, "params": self.params, "status": self.status,
            "duration_ms": round(self.duration_ms, 2), "row_count": self.row_count, "truncated": self.truncated,
            "cached": self.cached, "tables": self.tables, "limit_applied": self.limit_applied,
        }


class ResultCache:
    """Small thread-safe LRU + TTL cache keyed by (db file, db generation, sql, params)."""

    def __init__(self, max_entries: int, ttl_seconds: int) -> None:
        self.max_entries, self.ttl = max_entries, ttl_seconds
        self._data: OrderedDict[tuple, tuple[float, tuple]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = self.coalesced = 0
        self._inflight: dict[tuple, threading.Event] = {}

    def lead(self, key: tuple) -> tuple[bool, threading.Event]:
        """Single-flight (hardening iteration 10): the first caller for a missing key computes it; concurrent
        callers wait for that result instead of running the same query N times (cache stampede)."""
        with self._lock:
            ev = self._inflight.get(key)
            if ev is not None:
                self.coalesced += 1
                return False, ev
            ev = self._inflight[key] = threading.Event()
            return True, ev

    def done(self, key: tuple) -> None:
        with self._lock:
            ev = self._inflight.pop(key, None)
        if ev is not None:
            ev.set()

    def get(self, key: tuple):
        with self._lock:
            item = self._data.get(key)
            if item is None or time.monotonic() - item[0] > self.ttl:
                self._data.pop(key, None)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return item[1]

    def put(self, key: tuple, value: tuple) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._data), "hits": self.hits, "misses": self.misses, "coalesced": self.coalesced,
                    "in_flight": len(self._inflight), "max_entries": self.max_entries, "ttl_seconds": self.ttl}


_settings = get_settings()
cache = ResultCache(_settings.cache_max_entries, _settings.cache_ttl_seconds)


def execute(query: CompiledQuery, *, use_cache: bool = True, timeout_ms: int | None = None, max_rows: int | None = None) -> QueryRun:
    settings = get_settings()
    max_rows = max_rows or settings.max_result_rows
    timeout_ms = timeout_ms or settings.query_timeout_ms

    validation = validate_sql(query.sql, max_rows=max_rows)
    if not validation.valid:
        log.warning("sql_rejected", extra={"purpose": query.purpose, "reasons": validation.reasons})
        raise SQLValidationError("Query rejected by the SQL safety validator.", details={"reasons": validation.reasons, "sql": query.sql})

    db = get_db()
    key = (str(db.path), db.generation, validation.sql, tuple(sorted(query.params.items())))
    run = QueryRun(query.purpose, query.sql, dict(query.params), tables=validation.tables, limit_applied=validation.limit_applied)
    t0 = time.perf_counter()
    leader = False
    if use_cache:
        hit = cache.get(key)
        if hit is None:
            leader, ev = cache.lead(key)
            if not leader:
                ev.wait(timeout_ms / 1000.0 + 1.0)
                hit = cache.get(key)  # None if the leader failed: fall through and run it ourselves
        if hit is not None:
            run.columns, rows, run.truncated = hit
            run.rows = [dict(r) for r in rows]
            run.row_count, run.cached = len(run.rows), True
            run.duration_ms = (time.perf_counter() - t0) * 1000
            return run
    try:
        return _run_uncached(run, validation, query, db, key, use_cache=use_cache, timeout_ms=timeout_ms, max_rows=max_rows, t0=t0)
    finally:
        if leader:
            cache.done(key)


def _run_uncached(run: QueryRun, validation, query: CompiledQuery, db, key: tuple, *, use_cache: bool, timeout_ms: int,
                  max_rows: int, t0: float) -> QueryRun:
    settings = get_settings()

    deadline = time.perf_counter() + timeout_ms / 1000.0
    try:
        with db.readonly() as conn:
            conn.set_authorizer(_authorizer)
            conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 2_000)
            cur = conn.execute(validation.sql, query.params)
            columns = [c[0] for c in cur.description or []]
            raw = cur.fetchmany(max_rows + 1)
    except sqlite3.OperationalError as exc:
        msg = str(exc)
        if "interrupted" in msg:
            log.warning("query_timeout", extra={"purpose": query.purpose, "timeout_ms": timeout_ms})
            raise QueryTimeoutError(f"Query exceeded the {timeout_ms} ms execution limit and was cancelled.",
                                    details={"timeout_ms": timeout_ms, "sql": query.sql}) from exc
        if "not authorized" in msg or "authorization denied" in msg:
            raise SQLValidationError("Query blocked by the database authorizer (read-only policy).", details={"reasons": [msg], "sql": query.sql}) from exc
        raise QueryExecutionError(f"Query failed: {msg}", details={"sql": query.sql}) from exc
    except sqlite3.DatabaseError as exc:
        raise QueryExecutionError(f"Query failed: {exc}", details={"sql": query.sql}) from exc
    except MemoryError as exc:  # SQLite hit the process-wide hard heap limit (see DatabaseManager)
        log.warning("query_memory_limit", extra={"purpose": query.purpose})
        raise QueryResourceError("Query exceeded the database memory limit and was cancelled.",
                                 details={"heap_limit_mb": settings.sqlite_heap_limit_mb, "sql": query.sql}) from exc

    run.truncated = len(raw) > max_rows
    raw = raw[:max_rows]
    run.columns = columns
    run.rows = [dict(zip(columns, map(_cell, r))) for r in raw]
    run.row_count = len(run.rows)
    run.duration_ms = (time.perf_counter() - t0) * 1000
    if use_cache:
        cache.put(key, (columns, [tuple(r.items()) for r in run.rows], run.truncated))
    log.info("query_executed", extra={"purpose": query.purpose, "rows": run.row_count, "ms": round(run.duration_ms, 2)})
    return run
