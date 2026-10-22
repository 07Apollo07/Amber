"""Shared PostHog client lifecycle for the FastAPI application."""

import atexit

from fastapi import HTTPException, Request
from posthog import Posthog
from starlette.concurrency import run_in_threadpool

from amber.util.config import Settings

_posthog_client: Posthog | None = None


def initialize_posthog(settings: Settings) -> Posthog | None:
    """Create the process-wide PostHog client during FastAPI startup."""
    global _posthog_client

    if _posthog_client is not None:
        return _posthog_client

    if not settings.posthog_api_key or not settings.posthog_host:
        if settings.env == "dev":
            missing_var = "AMBER_POSTHOG_API_KEY" if not settings.posthog_api_key else "AMBER_POSTHOG_HOST"
            raise RuntimeError(
                f"{missing_var} variable required by PostHog is missing or un-configured, this causes events to be "
                f"silently missed. This error stops appearing once {missing_var} is configured"
            )
        return None

    _posthog_client = Posthog(
        project_api_key=settings.posthog_api_key,
        host=settings.posthog_host,
        enable_exception_autocapture=True,
    )
    atexit.register(_posthog_client.shutdown)
    return _posthog_client


def get_posthog_client() -> Posthog | None:
    """Return the process-wide client after FastAPI lifespan startup."""
    return _posthog_client


class PostHogRequestContextMiddleware:
    """Bind the authenticated Amber user to one PostHog context per HTTP request."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        app = scope["app"]
        client = getattr(app.state, "posthog_client", None)
        if client is None:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        try:
            # Reuse the app's authoritative session verification and database user lookup.
            from amber.util.security import current_user

            user = await run_in_threadpool(current_user, request, app.state.settings)
        except HTTPException:
            # Anonymous and rejected requests have no trustworthy user to identify.
            await self.app(scope, receive, send)
            return

        # The Amber database primary key is stable even if the Firebase account or profile changes.
        with client.new_context(fresh=True):
            client.identify_context(str(user["id"]))
            await self.app(scope, receive, send)
