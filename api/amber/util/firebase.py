"""Firebase Auth: exchange the verified Google ID token for a Firebase session cookie."""

import os
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import firebase_admin
import google.auth
import httpx
from firebase_admin import auth as fb_auth
from google.auth.exceptions import DefaultCredentialsError

from amber.util.config import Settings

SIGN_IN_WITH_IDP = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp"
APP_NAME = "amber"
API_DIR = Path(__file__).resolve().parents[2]  # the api folder, where .env lives

# uid -> ("revoked before" timestamp, cached until), see verify_session_cookie().
_revoked_before_cache: dict[str, tuple[float, float]] = {}


class SessionInvalid(Exception):
    """The session cookie is missing, expired, revoked, or the Firebase user is disabled."""


def init_firebase(settings: Settings) -> None:
    """Loads Google credentials and initializes the Firebase Admin app. Called once at startup,
    so a missing key fails immediately rather than at the first sign-in."""
    key_file = settings.google_application_credentials
    if key_file:
        path = Path(key_file).expanduser()
        if not path.is_absolute():
            path = API_DIR / path
        if not path.is_file():
            raise RuntimeError(f"GOOGLE_APPLICATION_CREDENTIALS points to {path}, which doesn't exist.")
        # Settings read .env into Python only; google.auth.default() looks at the real environment.
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)
    try:
        google.auth.default()
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "No Google credentials found for Firebase Admin. Set GOOGLE_APPLICATION_CREDENTIALS "
            "(in the environment or api/.env) to your service-account key file. In GCP the "
            "service account provides them."
        ) from exc
    try:
        firebase_admin.get_app(APP_NAME)
    except ValueError:  # not initialized yet
        firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id}, name=APP_NAME)


def _app() -> firebase_admin.App:
    return firebase_admin.get_app(APP_NAME)


def sign_in_with_google(settings: Settings, google_id_token: str) -> dict[str, str]:
    """Creates or signs in the Firebase user for this Google account (server side).
    Returns {"uid", "id_token"}."""
    resp = httpx.post(
        SIGN_IN_WITH_IDP,
        params={"key": settings.firebase_web_api_key.get_secret_value()},
        json={
            "postBody": f"id_token={google_id_token}&providerId=google.com",
            "requestUri": settings.public_origin,
            "returnSecureToken": True,
            "returnIdpCredential": False,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        # Google's message names the cause (e.g. INVALID_IDP_RESPONSE, API key restrictions); no token in it.
        try:
            message = resp.json().get("error", {}).get("message", "")
        except ValueError:
            message = ""
        raise SessionInvalid(f"signInWithIdp returned {resp.status_code}: {message}")
    body = resp.json()
    return {"uid": body["localId"], "id_token": body["idToken"]}


def create_session_cookie(settings: Settings, firebase_id_token: str) -> str:
    return fb_auth.create_session_cookie(
        firebase_id_token, expires_in=timedelta(days=settings.session_days), app=_app()
    )


def verify_session_cookie(settings: Settings, cookie: str) -> dict[str, Any]:
    """Verifies the signature and expiry locally on every call, then checks revocation.

    This is what check_revoked=True does, except the user's "revoked before" timestamp is
    cached for `revocation_cache_seconds` instead of fetched from Firebase on every request.
    """
    try:
        claims = fb_auth.verify_session_cookie(cookie, check_revoked=False, app=_app())
        if claims["iat"] < _revoked_before(settings, claims["uid"]):  # same comparison Firebase makes
            raise SessionInvalid("revoked")
        return claims
    except (
        fb_auth.InvalidSessionCookieError,
        fb_auth.ExpiredSessionCookieError,
        fb_auth.UserNotFoundError,
        ValueError,
    ) as exc:
        raise SessionInvalid(type(exc).__name__) from exc


def _revoked_before(settings: Settings, uid: str) -> float:
    now = time.monotonic()
    cached = _revoked_before_cache.get(uid)
    if cached and cached[1] > now:
        return cached[0]
    user = fb_auth.get_user(uid, app=_app())
    if user.disabled:
        raise SessionInvalid("disabled")
    valid_after = (user.tokens_valid_after_timestamp or 0) / 1000
    _revoked_before_cache[uid] = (valid_after, now + settings.revocation_cache_seconds)
    return valid_after


def revoke_all_sessions(uid: str) -> None:
    fb_auth.revoke_refresh_tokens(uid, app=_app())
    _revoked_before_cache.pop(uid, None)  # takes effect on this instance immediately
