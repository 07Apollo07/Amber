"""Per-client fixed-window rate limiting for the auth endpoints.

In-memory, so each API instance counts separately; Cloud Armor (Phase 7) adds a global limit.
Counts are approximate under concurrent requests, which is fine for a rate limit.
"""

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


def limit(bucket: str, max_hits: int, window_seconds: int):
    """FastAPI dependency: raises RateLimited once a client exceeds `max_hits` per window.

    Counts live on the app (app.state.rate_hits), keyed by (bucket, client IP, window).
    """

    def dependency(request: Request) -> None:
        hits: dict[tuple[str, str, int], int] = request.app.state.rate_hits
        window = int(time.monotonic() // window_seconds)
        if len(hits) > 10_000:  # drop old windows so memory stays bounded
            for key in [k for k in hits if k[2] != window]:
                hits.pop(key, None)
        key = (bucket, client_ip(request, request.app.state.settings) or "unknown", window)
        hits[key] = hits.get(key, 0) + 1
        if hits[key] > max_hits:
            raise RateLimited(window_seconds)

    return dependency
