from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from amber.api import admin, auth, collections, documents, drive, me
from amber.util.config import Settings, get_settings
from amber.util.firebase import init_firebase
from amber.util.ratelimit import RateLimited, rate_limited_response


def create_app(settings: Settings | None = None) -> FastAPI:
    """Run with `python main.py` from the api folder (see run() below)."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.settings = settings
        app.state.rate_hits = {}
        if settings.env != "test":  # tests never call Firebase, so they need no Google credentials
            init_firebase(settings)
        yield

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

    app.include_router(admin.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(documents.router)
    app.include_router(collections.router)
    app.include_router(drive.router)
    return app


def run() -> None:
    """Starts the API server. Auto-reloads on code changes in dev."""
    import os

    import uvicorn

    settings = get_settings()
    api_dir = os.path.dirname(os.path.abspath(__file__))
    uvicorn.run(
        "main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.env == "dev",
        reload_dirs=[api_dir] if settings.env == "dev" else None,
        # The client IP is resolved by amber/util/net.py from AMBER_TRUSTED_PROXIES only.
        proxy_headers=False,
    )


if __name__ == "__main__":
    run()
