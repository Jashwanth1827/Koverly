"""Minimal in-process rate limiter.

A token-bucket style sliding window keyed by identity (user id or client IP).
This is sufficient for a single-instance deployment; for horizontally scaled
deployments swap in a Redis-backed implementation behind the same interface.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from app.core.config import settings
from app.core.errors import RateLimitError


class RateLimiter:
    def __init__(self, limit_per_minute: int | None = None) -> None:
        self.limit = limit_per_minute or settings.RATE_LIMIT_PER_MINUTE
        self.window_seconds = 60.0
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, identity: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[identity]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                raise RateLimitError("Too many requests. Please slow down.")
            bucket.append(now)

    def reset(self, identity: str | None = None) -> None:
        with self._lock:
            if identity is None:
                self._hits.clear()
            else:
                self._hits.pop(identity, None)


rate_limiter = RateLimiter()
