from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

from amber.api import auth, me
from amber.util.config import Settings, get_settings
from amber.util.crypto import build_token_cipher
from amber.util.db import Database
from amber.util.firebase import FirebaseIdentity
from amber.util.google_oauth import GoogleOAuthClient
from amber.util.ratelimit import RateLimited, rate_limited_response


def create_app(settings: Settings | None = None, **overrides) -> FastAPI:
    """Run with `python -m amber.main` (see run() below).

    `overrides` (database, google, firebase, cipher) let tests swap external services."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        http = httpx.Client()
        state = app.state
        state.settings = settings
        state.rate_limiters = {}
        owns_db = "database" not in overrides
        state.database = Database.from_settings(settings) if owns_db else overrides["database"]
        state.google = overrides.get("google") or GoogleOAuthClient(settings, http)
        state.firebase = overrides.get("firebase") or FirebaseIdentity(settings, http)
        state.cipher = overrides.get("cipher") or build_token_cipher(settings)
        try:
            yield
        finally:
            http.close()  # noqa: ASYNC212 (shutdown only; nothing else is running)
            if owns_db:
                state.database.close()

    is_prod = settings.env == "prod"
    app = FastAPI(
        title="Amber API",
        lifespan=lifespan,
        docs_url=None if is_prod else "/api/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/api/openapi.json",
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")  # API responses are per-user
        return response

    app.add_exception_handler(RateLimited, rate_limited_response)  # type: ignore[arg-type]

    @app.get("/api/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(me.router)
    return app


def run() -> None:
    """Starts the API server. Auto-reloads on code changes in dev."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "amber.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.env == "dev",
        # The client IP is resolved by amber/util/net.py from AMBER_TRUSTED_PROXIES only.
        proxy_headers=False,
    )


if __name__ == "__main__":
    run()
