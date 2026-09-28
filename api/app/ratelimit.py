"""A small in-process rate limiter for the endpoints worth guessing at.

The API runs as a single uvicorn process on one instance (render.yaml), so
per-process memory is the whole picture — no shared store needed. If it
ever scales out, each instance limits on its own, which only makes the
limits looser, never wrong.

Keyed by client IP. Behind Render's proxy the real client is the first
X-Forwarded-For hop; a client can forge that header, but only to spread its
own requests across made-up keys, which the global cap still bounds.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

from .config import settings

# Every bucket together, so forged X-Forwarded-For values can't grow the
# table without bound. Oldest buckets are dropped first.
_MAX_KEYS = 10_000


class _Limiter:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self.hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits.get(key)
        if q is None:
            if len(self.hits) >= _MAX_KEYS:
                self.hits.pop(next(iter(self.hits)))
            q = self.hits[key] = deque()
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window_s: float = 60.0) -> Callable[[Request], None]:
    """A FastAPI dependency allowing `limit` requests per `window_s` per client."""
    limiter = _Limiter(limit, window_s)

    def dependency(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        if not limiter.check(f"{name}:{_client_key(request)}"):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests — slow down a little."
            )

    return dependency
