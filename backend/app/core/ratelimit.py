"""Pluggable rate limiting (hardening iteration 7).

The limiter is written against a tiny backend interface so the deployment can scale out without
touching call sites:

* ``MemoryRateLimitBackend`` (default): sliding window per key, in-process. Correct for a single
  API process. Memory is **bounded**: expired keys are swept periodically and the number of tracked
  keys is capped (oldest evicted first). Before this iteration every client IP ever seen stayed in
  memory forever (50,000 one-off IPs -> 50,000 retained keys).
* A shared backend (for N API replicas) implements the same ``hit`` method on a shared store, for
  example a Redis sorted set per key (``ZREMRANGEBYSCORE`` / ``ZCARD`` / ``ZADD`` / ``EXPIRE`` in
  one ``MULTI``) or a SQL table. Register it with ``register_backend`` and select it with
  ``PAYINSIGHT_RATE_LIMIT_BACKEND``. None ships here: the project constraints rule out Redis.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Callable, Protocol

from .errors import RateLimitError


class RateLimitBackend(Protocol):
    def hit(self, key: str, limit: int, window_s: float) -> float | None:
        """Record one event for ``key``. Return ``None`` if allowed, else seconds until a slot frees up."""

    def reset(self) -> None: ...

    def size(self) -> int: ...


class MemoryRateLimitBackend:
    def __init__(self, max_keys: int = 100_000, sweep_every: int = 1_000) -> None:
        self.max_keys, self.sweep_every = max_keys, sweep_every
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._calls = 0
        self._max_window = 0.0

    def hit(self, key: str, limit: int, window_s: float) -> float | None:
        now = time.perf_counter()  # high resolution: time.monotonic() ticks every ~15.6 ms on Windows
        with self._lock:
            self._max_window = max(self._max_window, window_s)
            self._calls += 1
            if self._calls % self.sweep_every == 0:
                self._sweep(now)
            q = self._hits.get(key)
            if q is None:
                q = self._hits[key] = deque()
            else:
                self._hits.move_to_end(key)
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, window_s - (now - q[0]))
            q.append(now)
            while len(self._hits) > self.max_keys:  # hard memory bound: evict least recently active key
                self._hits.popitem(last=False)
            return None

    def _sweep(self, now: float) -> None:
        dead = [k for k, q in self._hits.items() if not q or now - q[-1] > self._max_window]
        for k in dead:
            del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._hits)


_BACKENDS: dict[str, Callable[[], RateLimitBackend]] = {"memory": MemoryRateLimitBackend}


def register_backend(name: str, factory: Callable[[], RateLimitBackend]) -> None:
    _BACKENDS[name] = factory


def create_backend(name: str) -> RateLimitBackend:
    try:
        return _BACKENDS[name]()
    except KeyError:
        raise ValueError(f"Unknown rate-limit backend {name!r}; registered: {sorted(_BACKENDS)}") from None


class RateLimiter:
    """Sliding-window limiter keyed by (bucket, client)."""

    def __init__(self, backend: RateLimitBackend | None = None) -> None:
        self.backend = backend or MemoryRateLimitBackend()

    def check(self, bucket: str, key: str, limit: int, window_s: float = 60.0) -> None:
        retry = self.backend.hit(f"{bucket}:{key}", limit, window_s)
        if retry is not None:
            secs = int(retry) + 1
            raise RateLimitError("Too many attempts. Please wait and try again.",
                                 details={"retry_after_seconds": secs}, headers={"Retry-After": str(secs)})

    def reset(self) -> None:
        self.backend.reset()
