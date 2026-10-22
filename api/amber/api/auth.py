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

from amber import repository
from amber.models import can_import_folders, can_manage_drive_sharing, drive_connected
from amber.util import audit, drive_sync, firebase, google_oauth
from amber.util.config import Settings
from amber.util.crypto import decrypt_token, encrypt_token
from amber.util.db import Connection
from amber.util.firebase import SessionInvalid
from amber.util.google_oauth import OAuthError, RevokeFailed, new_pkce_pair
from amber.util.posthog import capture_event, get_posthog_client
from amber.util.ratelimit import limit
from amber.util.security import (
    CsrfProtected,
    CurrentUser,
    DbDep,
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
    return_to: str | None = None,
    consent: bool = False,
    reconnect: bool = False,
) -> RedirectResponse:
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = new_pkce_pair()
    force_consent = consent or reconnect
    url = google_oauth.authorization_url(
        settings, state=state, nonce=nonce, code_challenge=challenge, force_consent=force_consent
    )
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


def _upsert_user(conn: Connection, settings: Settings, identity: dict, firebase_uid: str) -> dict:
    """Creates the user on first sign-in; afterwards profile fields follow Google.

    Role and status are Amber's own. A bootstrap admin email only grants admin when the
    account is first created, so a reassigned mailbox can't inherit admin later.
    A deactivated user's row is returned untouched.
    """
    profile = {
        "firebase_uid": firebase_uid,
        "email": identity["email"],
        "domain": identity["domain"],
        "name": identity["name"],
        "picture_url": identity["picture"],
    }
    existing = repository.lock_user_by_google_sub(conn, identity["sub"])
    if existing is None:
        # An admin may have added this person's email in advance. Their first sign-in claims that account.
        pending = repository.lock_pending_user_by_email(conn, identity["email"])
        if pending is not None:
            repository.claim_pending_user(conn, pending["id"], google_sub=identity["sub"])
            existing = repository.lock_user_by_google_sub(conn, identity["sub"])
            capture_event("user_signed_up", pending["id"], invited_by_admin=True, role=pending["role"])
    if existing is None:
        role = "admin" if identity["email"] in settings.bootstrap_admins else "member"
        created = repository.insert_user(conn, google_sub=identity["sub"], role=role, **profile)
        if created is not None:
            capture_event(
                "user_signed_up",
                created["id"],
                invited_by_admin=False,
                role=role,
                is_bootstrap_admin=role == "admin",
                email_domain_type="workspace" if identity["domain"] else "personal",
            )
            return created
        existing = repository.lock_user_by_google_sub(conn, identity["sub"])  # lost a race: use the winner's row
        if existing is None:
            raise LookupError("user insert conflicted but no row found")
    if existing["status"] != "active":
        return existing
    return repository.update_user_profile(conn, existing["id"], role=existing["role"], **profile)


@router.get("/google/callback", dependencies=[_sign_in_limit])
def google_callback(
    request: Request,
    settings: SettingsDep,
    conn: DbDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    pending = _read_state(request, settings)
    if pending is None or state is None or not secrets.compare_digest(state, pending.get("state", "")):
        return _fail(settings, "state")
    if error:
        return _fail(settings, "denied" if error == "access_denied" else "google")
    if not code:
        return _fail(settings, "google")

    try:
        tokens = google_oauth.exchange_code(settings, code, pending["verifier"])
        identity = google_oauth.verify_id_token(settings, tokens["id_token"], pending["nonce"])
    except OAuthError as exc:
        return _fail(settings, exc.code)

    try:
        fb = firebase.sign_in_with_google(settings, tokens["id_token"])
    except SessionInvalid:
        return _fail(settings, "firebase_signin")

    user = _upsert_user(conn, settings, identity, fb["uid"])

    if user["status"] != "active":
        audit.record(conn, request, "auth.login_blocked", user=user, detail={"reason": "deactivated"})
        conn.commit()
        return _fail(settings, "deactivated")

    stored = repository.get_token(conn, user["id"])
    if tokens["refresh_token"]:
        blob, key_version = encrypt_token(settings, tokens["refresh_token"], aad=str(user["id"]))
        repository.save_token(conn, user["id"], encrypted=blob, key_version=key_version, scopes=tokens["scopes"])
    elif (
        stored is not None
        and not (can_manage_drive_sharing(stored["scopes"]) and can_import_folders(stored["scopes"]))
        and not pending["consent"]
    ):
        # Signed in before Amber asked for its current Drive scopes (drive.file, drive.readonly). The stored refresh
        # token still carries the old ones, so ask again with prompt=consent to get a new one. Nothing is saved until
        # that round completes.
        conn.rollback()
        response = RedirectResponse(
            f"/api/auth/google/start?consent=true&return_to={quote(pending['return_to'])}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        _clear_state(response, settings)
        return response
    elif stored is not None:
        repository.update_token_scopes(conn, user["id"], tokens["scopes"])  # what the user has granted right now
    elif not pending["consent"]:
        # Google skips the refresh token for returning users; ask once more with prompt=consent.
        # Nothing is saved until that second round completes.
        conn.rollback()
        response = RedirectResponse(
            f"/api/auth/google/start?consent=true&return_to={quote(pending['return_to'])}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        _clear_state(response, settings)
        return response

    try:
        session_cookie = firebase.create_session_cookie(settings, fb["id_token"])
    except Exception as exc:
        # Firebase's own message is generic; Google's reply (which names the missing permission) is on the cause.
        reply = getattr(getattr(getattr(exc, "cause", None), "http_response", None), "text", "")
        log.error("Creating the Firebase session cookie failed: %s: %s Google said: %s", type(exc).__name__, exc, reply[:500])
        conn.rollback()
        return _fail(settings, "firebase_session")

    repository.touch_last_login(conn, user["id"])
    has_refresh_token = tokens["refresh_token"] is not None or stored is not None
    audit.record(
        conn,
        request,
        "auth.login",
        user=user,
        detail={"drive_connected": drive_connected(has_refresh_token, tokens["scopes"])},
    )
    conn.commit()

    if has_refresh_token and drive_connected(True, tokens["scopes"]):
        try:
            drive_sync.ensure_drive_watch(user["id"], conn, settings)
        except Exception as exc:
            log.warning("Could not start Drive change notifications for user %s: %s", user["id"], exc)

    client = get_posthog_client()
    if client:
        with client.new_context(fresh=True):
            client.identify_context(str(user["id"]))
            client.capture(
                "user_logged_in",
                properties={"drive_connected": drive_connected(has_refresh_token, tokens["scopes"])},
            )

    response = _same_site_redirect(pending["return_to"])
    set_session_cookies(response, settings, session_cookie)
    _clear_state(response, settings)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_session_limit, CsrfProtected])
def logout(request: Request, settings: SettingsDep, conn: DbDep) -> Response:
    """Signs out this browser. The session cookie is also revoked server-side, so a copy of
    it (e.g. stolen) stops working too; other devices stay signed in."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        cookie, claims = verified_session(request, settings, conn)
    except HTTPException:
        cookie = None  # already signed out or expired: just clear the cookies
    if cookie is not None:
        repository.revoke_session(conn, session_hash(cookie), datetime.fromtimestamp(claims["exp"], UTC))
        user = repository.get_user_by_firebase_uid(conn, claims["uid"])
        audit.record(conn, request, "auth.logout", user=user)
        conn.commit()
        client = get_posthog_client()
        if client:
            client.capture("user_logged_out", properties={"all_sessions": False})
    clear_session_cookies(response, settings)
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_session_limit, CsrfProtected])
def logout_all(request: Request, user: CurrentUser, settings: SettingsDep, conn: DbDep) -> Response:
    # Revokes every Firebase session for this user; verify_session_cookie() then rejects them.
    firebase.revoke_all_sessions(user["firebase_uid"])
    audit.record(conn, request, "auth.logout_all", user=user)
    conn.commit()
    client = get_posthog_client()
    if client:
        client.capture("user_logged_out", properties={"all_sessions": True})
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, settings)
    return response


@router.post("/google/disconnect", dependencies=[_session_limit, CsrfProtected])
def disconnect_drive(request: Request, user: CurrentUser, settings: SettingsDep, conn: DbDep) -> dict[str, bool]:
    """Revokes Amber's Drive access at Google, then deletes the stored token.

    If Google can't confirm the revocation, the token is kept (502) so the user can retry.
    If the stored token can't be decrypted, Amber's copy is deleted and the response says
    the grant may still exist at Google, so the UI can point the user to their Google account.
    """
    stored = repository.get_token(conn, user["id"])
    drive_sync.stop_drive_watch(user["id"], conn)
    repository.delete_drive_sync_state(conn, user["id"])
    revoked = True
    if stored is not None:
        drive_sync.stop_drive_watch(user["id"], conn)
        repository.delete_drive_sync_state(conn, user["id"])
        try:
            refresh_token = decrypt_token(settings, stored["encrypted_refresh_token"], aad=str(user["id"]))
        except Exception as exc:
            log.warning("Stored Drive token for user %s is unreadable: %s", user["id"], type(exc).__name__)
            revoked = False
        else:
            try:
                google_oauth.revoke(refresh_token)
            except RevokeFailed:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY, "Couldn't reach Google to remove access. Please try again."
                ) from None
        repository.delete_token(conn, user["id"])
    audit.record(conn, request, "drive.disconnect", user=user, detail={"revoked_at_google": revoked})
    conn.commit()
    client = get_posthog_client()
    if client:
        client.capture("drive_disconnected", properties={"revoked_at_google": revoked})
    return {"revoked_at_google": revoked}
