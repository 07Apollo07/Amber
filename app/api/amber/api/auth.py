"""Google sign-in (with Drive permission), Firebase session cookies, sign-out, Drive disconnect.

Flow:
  1. GET  /api/auth/google/start     -> 302 to Google consent (PKCE, state, nonce, offline access)
  2. GET  /api/auth/google/callback  -> exchange code, verify ID token, store encrypted refresh
                                        token, sign in to Firebase server-side, set session cookie
  3. POST /api/auth/logout | /logout-all | /google/disconnect  (CSRF-protected)

No Google or Firebase token is ever handed to browser JavaScript.
"""

import html
import json
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from amber import repository
from amber.models import User, drive_connected
from amber.util import audit
from amber.util.config import Settings
from amber.util.db import Db
from amber.util.firebase import SessionInvalid
from amber.util.google_oauth import GoogleIdentity, OAuthError, RevokeFailed, new_pkce_pair
from amber.util.ratelimit import limit
from amber.util.security import (
    CipherDep,
    CsrfProtected,
    CurrentUser,
    DbDep,
    FirebaseDep,
    GoogleDep,
    SettingsDep,
    clear_session_cookies,
    cookie_names,
    session_hash,
    set_session_cookies,
    verified_session,
)

# Per client IP: sign-in redirects, and the session-changing POSTs.
_sign_in_limit = Depends(limit("auth.sign_in", max_hits=20, window_seconds=60))
_session_limit = Depends(limit("auth.session", max_hits=10, window_seconds=60))

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger(__name__)

STATE_TTL = timedelta(minutes=10)
DEFAULT_RETURN_TO = "/search"
# App-relative paths only: blocks open redirects (`//evil.com`, `https://…`, `/\evil.com`) and /api.
_SAFE_PATH = re.compile(r"^/(?!/|\\|api(?:/|$))[A-Za-z0-9\-._~/?=&%]*$")


def safe_return_to(value: str | None) -> str:
    return value if value and _SAFE_PATH.match(value) else DEFAULT_RETURN_TO


# ---- short-lived OAuth state cookie (encrypted + authenticated + timestamped) ----


def _fernet(settings: Settings) -> Fernet:
    return Fernet(settings.state_cookie_key.get_secret_value())


def _write_state(response: Response, settings: Settings, data: dict) -> None:
    _, _, oauth_name = cookie_names(settings)
    token = _fernet(settings).encrypt(json.dumps(data).encode()).decode()
    # Lax (not Strict) because Google's redirect back to us is a cross-site top-level navigation.
    response.set_cookie(
        oauth_name,
        token,
        max_age=int(STATE_TTL.total_seconds()),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _read_state(request: Request, settings: Settings) -> dict | None:
    _, _, oauth_name = cookie_names(settings)
    raw = request.cookies.get(oauth_name)
    if not raw:
        return None
    try:
        return json.loads(_fernet(settings).decrypt(raw.encode(), ttl=int(STATE_TTL.total_seconds())))
    except (InvalidToken, ValueError):
        return None


def _clear_state(response: Response, settings: Settings) -> None:
    _, _, oauth_name = cookie_names(settings)
    response.delete_cookie(oauth_name, path="/", secure=settings.cookie_secure, samesite="lax")


def _fail(settings: Settings, code: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?error={quote(code)}", status_code=status.HTTP_303_SEE_OTHER)
    _clear_state(response, settings)
    return response


def _same_site_redirect(path: str) -> HTMLResponse:
    """Lands the user on `path` via a same-origin navigation.

    A plain 302 here would continue the redirect chain that started on accounts.google.com,
    so browsers would treat the next request as cross-site and withhold the new
    SameSite=Strict session cookie. A meta refresh starts a fresh, same-site navigation.
    """
    target = html.escape(path, quote=True)
    body = (
        '<!doctype html><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={target}">'
        f'<title>Signing in…</title><p>Signing you in… <a href="{target}">Continue</a></p>'
    )
    return HTMLResponse(body, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


# ---- routes ----
# Plain `def` handlers: FastAPI runs them in its threadpool, so blocking psycopg2 and
# Google/Firebase calls don't stall the event loop.


@router.get("/google/start", dependencies=[_sign_in_limit])
def google_start(
    settings: SettingsDep,
    google: GoogleDep,
    return_to: str | None = None,
    consent: bool = False,
    reconnect: bool = False,
) -> RedirectResponse:
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = new_pkce_pair()
    force_consent = consent or reconnect
    url = google.authorization_url(state=state, nonce=nonce, code_challenge=challenge, force_consent=force_consent)
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    _write_state(
        response,
        settings,
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "return_to": safe_return_to(return_to),
            "consent": force_consent,
        },
    )
    return response


def _upsert_user(db: Db, settings: Settings, identity: GoogleIdentity, firebase_uid: str) -> User:
    """Creates the user on first sign-in; afterwards profile fields follow Google.

    Role and status are Amber's own. A bootstrap admin email only grants admin when the
    account is first created, so a reassigned mailbox can't inherit admin later.
    A deactivated user's row is returned untouched.
    """
    profile = {
        "firebase_uid": firebase_uid,
        "email": identity.email,
        "domain": identity.domain,
        "name": identity.name,
        "picture_url": identity.picture,
    }
    existing = repository.lock_user_by_google_sub(db, identity.sub)
    if existing is None:
        role = "admin" if identity.email in settings.bootstrap_admins else "member"
        created = repository.insert_user(db, google_sub=identity.sub, role=role, **profile)
        if created is not None:
            return created
        existing = repository.lock_user_by_google_sub(db, identity.sub)  # lost a race: use the winner's row
        if existing is None:
            raise LookupError("user insert conflicted but no row found")
    if existing.status != "active":
        return existing
    return repository.update_user_profile(db, existing.id, role=existing.role, **profile)


@router.get("/google/callback", dependencies=[_sign_in_limit])
def google_callback(
    request: Request,
    settings: SettingsDep,
    db: DbDep,
    google: GoogleDep,
    firebase: FirebaseDep,
    cipher: CipherDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    pending = _read_state(request, settings)
    if pending is None or state is None or not secrets.compare_digest(state, pending["state"]):
        return _fail(settings, "state")
    if error:
        return _fail(settings, "denied" if error == "access_denied" else "google")
    if not code:
        return _fail(settings, "google")

    try:
        tokens = google.exchange_code(code, pending["verifier"])
        identity = google.verify_id_token(tokens.id_token, pending["nonce"])
    except OAuthError as exc:
        return _fail(settings, exc.code)

    try:
        fb = firebase.sign_in_with_google(tokens.id_token)
    except SessionInvalid as exc:
        log.error("Firebase sign-in failed: %s", exc)
        return _fail(settings, "firebase_signin")

    user = _upsert_user(db, settings, identity, fb.uid)

    if user.status != "active":
        audit.record(db, request, "auth.login_blocked", user=user, detail={"reason": "deactivated"})
        db.commit()
        return _fail(settings, "deactivated")

    stored = repository.get_token(db, user.id)
    if tokens.refresh_token:
        blob, key_version = cipher.encrypt(tokens.refresh_token, aad=str(user.id))
        repository.save_token(db, user.id, encrypted=blob, key_version=key_version, scopes=tokens.scopes)
    elif stored is not None:
        repository.update_token_scopes(db, user.id, tokens.scopes)  # what the user has granted right now
    elif not pending["consent"]:
        # Google skips the refresh token for returning users; ask once more with prompt=consent.
        # Nothing is saved until that second round completes.
        db.rollback()
        response = RedirectResponse(
            f"/api/auth/google/start?consent=true&return_to={quote(pending['return_to'])}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        _clear_state(response, settings)
        return response

    try:
        session_cookie = firebase.create_session_cookie(fb.id_token)
    except Exception as exc:
        # Usually missing or under-privileged Google credentials for Firebase Admin.
        log.error("Creating the Firebase session cookie failed: %s: %s", type(exc).__name__, exc)
        db.rollback()
        return _fail(settings, "firebase_session")

    repository.touch_last_login(db, user.id)
    has_refresh_token = tokens.refresh_token is not None or stored is not None
    audit.record(
        db,
        request,
        "auth.login",
        user=user,
        detail={"drive_connected": drive_connected(has_refresh_token, tokens.scopes)},
    )
    db.commit()

    response = _same_site_redirect(pending["return_to"])
    set_session_cookies(response, settings, session_cookie)
    _clear_state(response, settings)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_session_limit, CsrfProtected])
def logout(request: Request, settings: SettingsDep, db: DbDep, firebase: FirebaseDep) -> Response:
    """Signs out this browser. The session cookie is also revoked server-side, so a copy of
    it (e.g. stolen) stops working too; other devices stay signed in."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        cookie, claims = verified_session(request, settings, db, firebase)
    except HTTPException:
        cookie = None  # already signed out or expired: just clear the cookies
    if cookie is not None:
        repository.revoke_session(db, session_hash(cookie), datetime.fromtimestamp(claims["exp"], UTC))
        user = repository.get_user_by_firebase_uid(db, claims["uid"])
        audit.record(db, request, "auth.logout", user=user)
        db.commit()
    clear_session_cookies(response, settings)
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_session_limit, CsrfProtected])
def logout_all(
    request: Request, user: CurrentUser, settings: SettingsDep, db: DbDep, firebase: FirebaseDep
) -> Response:
    # Revokes every Firebase session for this user; verify_session_cookie(check_revoked=True) then rejects them.
    firebase.revoke_all_sessions(user.firebase_uid)
    audit.record(db, request, "auth.logout_all", user=user)
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, settings)
    return response


class DisconnectOut(BaseModel):
    revoked_at_google: bool


@router.post("/google/disconnect", dependencies=[_session_limit, CsrfProtected])
def disconnect_drive(
    request: Request, user: CurrentUser, db: DbDep, google: GoogleDep, cipher: CipherDep
) -> DisconnectOut:
    """Revokes Amber's Drive access at Google, then deletes the stored token.

    If Google can't confirm the revocation, the token is kept (502) so the user can retry.
    If the stored token can't be decrypted, Amber's copy is deleted and the response says
    the grant may still exist at Google, so the UI can point the user to their Google account.
    """
    stored = repository.get_token(db, user.id)
    revoked = True
    if stored is not None:
        try:
            refresh_token = cipher.decrypt(stored.encrypted_refresh_token, aad=str(user.id))
        except Exception as exc:
            log.warning("Stored Drive token for user %s is unreadable: %s", user.id, type(exc).__name__)
            revoked = False
        else:
            try:
                google.revoke(refresh_token)
            except RevokeFailed:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY, "Couldn't reach Google to remove access. Please try again."
                ) from None
        repository.delete_token(db, user.id)
    audit.record(db, request, "drive.disconnect", user=user, detail={"revoked_at_google": revoked})
    db.commit()
    return DisconnectOut(revoked_at_google=revoked)
