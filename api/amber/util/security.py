"""Session cookies, CSRF protection, and the current-user / admin dependencies."""

import hashlib
import hmac
import secrets
from collections.abc import Generator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Response, status

from amber import repository
from amber.util import db, firebase
from amber.util.config import Settings
from amber.util.db import Connection
from amber.util.firebase import SessionInvalid

CSRF_HEADER = "X-Amber-CSRF"


def cookie_names(settings: Settings) -> tuple[str, str, str]:
    """(session, csrf, oauth-state).

    `__Host-` pins cookies to this exact origin, path / and Secure. Browsers only accept the
    prefix over https, so plain-http local dev (http://localhost) uses unprefixed names; the
    cookies there are still Secure, HttpOnly and SameSite.
    """
    https = settings.public_origin.startswith("https://")
    prefix = "__Host-" if settings.cookie_secure and https else ""
    return f"{prefix}amber_session", f"{prefix}amber_csrf", f"{prefix}amber_oauth"


# ---- request dependencies ----


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Generator[Connection, None, None]:
    """One connection per request; uncommitted work is discarded when it closes."""
    settings = request.app.state.settings
    with db.connect(settings) as conn:
        yield conn


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbDep = Annotated[Connection, Depends(get_db)]


# ---- cookies ----


def set_session_cookies(response: Response, settings: Settings, session_cookie: str) -> None:
    session_name, csrf_name, _ = cookie_names(settings)
    max_age = settings.session_days * 24 * 3600
    response.set_cookie(
        session_name,
        session_cookie,
        max_age=max_age,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    # Readable by the web app so it can echo it in the X-Amber-CSRF header (double submit).
    response.set_cookie(
        csrf_name,
        secrets.token_urlsafe(32),
        max_age=max_age,
        path="/",
        secure=settings.cookie_secure,
        httponly=False,
        samesite="strict",
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    session_name, csrf_name, _ = cookie_names(settings)
    for name in (session_name, csrf_name):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="strict")


# ---- CSRF ----


def require_csrf(request: Request, settings: SettingsDep) -> None:
    """For state-changing requests: same-origin check plus double-submit token."""
    origin = request.headers.get("origin")
    if origin is not None and origin != settings.public_origin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-origin request blocked")
    _, csrf_name, _ = cookie_names(settings)
    cookie = request.cookies.get(csrf_name, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token")


# ---- current user ----


def session_hash(cookie: str) -> bytes:
    return hashlib.sha256(cookie.encode()).digest()


def verified_session(request: Request, settings: Settings, conn: Connection | None = None) -> tuple[str, dict]:
    """Returns (cookie, claims) for a valid, unrevoked session cookie, or raises 401."""
    session_name, _, _ = cookie_names(settings)
    cookie = request.cookies.get(session_name)
    if not cookie:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        claims = firebase.verify_session_cookie(settings, cookie)  # signature, expiry, revoke-all
    except SessionInvalid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired") from None
    
    if conn is not None:
        if repository.is_session_revoked(conn, session_hash(cookie)):  # signed out on this device
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    else:
        with db.connect(settings) as c:
            if repository.is_session_revoked(c, session_hash(cookie)):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    return cookie, claims


def current_user(request: Request, settings: SettingsDep) -> dict[str, Any]:
    session_name, _, _ = cookie_names(settings)
    cookie = request.cookies.get(session_name)
    if not cookie:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")

    with db.connect(settings) as conn:
        _, claims = verified_session(request, settings, conn)
        user = repository.get_user_by_firebase_uid(conn, claims["uid"])
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
        if user["status"] != "active":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account deactivated")
        return user


CurrentUser = Annotated[dict[str, Any], Depends(current_user)]


def require_admin(user: CurrentUser) -> dict[str, Any]:
    # Roles come from Postgres, never from client-supplied claims.
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return user


AdminUser = Annotated[dict[str, Any], Depends(require_admin)]
CsrfProtected = Depends(require_csrf)
