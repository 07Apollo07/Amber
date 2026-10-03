"""Firebase Auth: exchange the verified Google ID token for a Firebase session cookie."""

import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import firebase_admin
import google.auth
import httpx
from firebase_admin import auth as fb_auth
from google.auth.exceptions import DefaultCredentialsError

from amber.util.config import Settings

SIGN_IN_WITH_IDP = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp"


def _require_google_credentials() -> None:
    """Firebase Admin calls (session cookies, revocation) need Google credentials. Fail at
    startup with instructions rather than at the first sign-in."""
    try:
        google.auth.default()
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "No Google credentials found for Firebase Admin. Locally run "
            "`gcloud auth application-default login` (then `gcloud auth application-default "
            "set-quota-project <firebase-project-id>`), or set GOOGLE_APPLICATION_CREDENTIALS. "
            "In GCP the service account provides them."
        ) from exc


class SessionInvalid(Exception):
    """The session cookie is missing, expired, revoked, or the Firebase user is disabled."""


@dataclass(frozen=True)
class FirebaseSignIn:
    uid: str
    id_token: str


class FirebaseIdentity:
    def __init__(self, settings: Settings, http: httpx.Client):
        self._s = settings
        self._http = http
        self._valid_after: dict[str, tuple[float, float]] = {}  # uid -> (revoked-before ts, cached until)
        self._lock = threading.Lock()
        _require_google_credentials()
        try:
            self._app = firebase_admin.get_app("amber")
        except ValueError:
            # Application Default Credentials: the Cloud Run service account in prod. No JSON keys.
            self._app = firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id}, name="amber")

    def sign_in_with_google(self, google_id_token: str) -> FirebaseSignIn:
        """Creates or signs in the Firebase user for this Google account (server side)."""
        resp = self._http.post(
            SIGN_IN_WITH_IDP,
            params={"key": self._s.firebase_web_api_key.get_secret_value()},
            json={
                "postBody": f"id_token={google_id_token}&providerId=google.com",
                "requestUri": self._s.public_origin,
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
        return FirebaseSignIn(uid=body["localId"], id_token=body["idToken"])

    def create_session_cookie(self, firebase_id_token: str) -> str:
        return fb_auth.create_session_cookie(
            firebase_id_token, expires_in=timedelta(days=self._s.session_days), app=self._app
        )

    def verify_session_cookie(self, cookie: str) -> dict[str, Any]:
        """Verifies the signature and expiry locally on every call, then checks revocation.

        This is what check_revoked=True does, except the user's "revoked before" timestamp
        is cached for `revocation_cache_seconds` instead of fetched from Firebase on
        every request.
        """
        try:
            claims = fb_auth.verify_session_cookie(cookie, check_revoked=False, app=self._app)
            if claims["iat"] < self._revoked_before(claims["uid"]):  # same comparison Firebase makes
                raise SessionInvalid("revoked")
            return claims
        except (
            fb_auth.InvalidSessionCookieError,
            fb_auth.ExpiredSessionCookieError,
            fb_auth.UserNotFoundError,
            ValueError,
        ) as exc:
            raise SessionInvalid(type(exc).__name__) from exc

    def _revoked_before(self, uid: str) -> float:
        now = time.monotonic()
        with self._lock:
            cached = self._valid_after.get(uid)
        if cached and cached[1] > now:
            return cached[0]
        user = fb_auth.get_user(uid, app=self._app)
        if user.disabled:
            raise SessionInvalid("disabled")
        valid_after = (user.tokens_valid_after_timestamp or 0) / 1000
        with self._lock:
            self._valid_after[uid] = (valid_after, now + self._s.revocation_cache_seconds)
        return valid_after

    def revoke_all_sessions(self, uid: str) -> None:
        fb_auth.revoke_refresh_tokens(uid, app=self._app)
        with self._lock:
            self._valid_after.pop(uid, None)  # takes effect on this instance immediately
