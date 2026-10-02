"""Per-client fixed-window rate limiting for the auth endpoints.

In-memory, so each API instance counts separately; Cloud Armor (Phase 7) adds a global limit.
"""

import threading
import time

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from amber.util.net import client_ip


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


def rate_limited_response(request: Request, exc: RateLimited) -> Response:
    """Sign-in is a browser navigation, so send it back to the login page; API calls get a 429."""
    if request.method == "GET":
        return RedirectResponse("/login?error=rate_limited", status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse(
        {"detail": "Too many attempts. Please wait a minute and try again."},
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(exc.retry_after)},
    )


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Records a request; returns False once `key` is over the limit for this window."""
        window = int(time.monotonic() // self.window)
        with self._lock:
            if len(self._hits) > 10_000:  # drop old windows so memory stays bounded
                self._hits = {k: v for k, v in self._hits.items() if k[1] == window}
            count = self._hits.get((key, window), 0) + 1
            self._hits[(key, window)] = count
        return count <= self.limit


def limit(name: str, max_hits: int, window_seconds: int):
    """FastAPI dependency: 429 once a client exceeds `max_hits` per window on bucket `name`.

    Counters live on the app (app.state.rate_limiters), so each app instance starts fresh.
    """

    def dependency(request: Request) -> None:
        limiters: dict[str, RateLimiter] = request.app.state.rate_limiters
        limiter = limiters.setdefault(name, RateLimiter(max_hits, window_seconds))
        key = client_ip(request, request.app.state.settings) or "unknown"
        if not limiter.hit(key):
            raise RateLimited(limiter.window)

    return dependency
