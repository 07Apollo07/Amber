"""Google OAuth 2.0 authorization-code flow with PKCE (server side, confidential client)."""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from amber.models import DRIVE_FILE_SCOPE
from amber.util.config import Settings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 (a URL, not a secret)
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Sign-in and the Drive permission are requested together, on one consent screen.
SCOPES = ["openid", "email", "profile", DRIVE_FILE_SCOPE]


class RevokeFailed(Exception):
    """Google didn't confirm the revocation (network error or unexpected response)."""


class OAuthError(Exception):
    """Anything wrong with the code exchange or the ID token. `code` is safe to show the user."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class GoogleTokens:
    id_token: str
    refresh_token: str | None
    scopes: str


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str
    picture: str | None
    domain: str | None


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class GoogleOAuthClient:
    def __init__(self, settings: Settings, http: httpx.Client):
        self._s = settings
        self._http = http

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str, force_consent: bool) -> str:
        params = {
            "client_id": self._s.google_oauth_client_id,
            "redirect_uri": self._s.oauth_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",  # needed for a refresh token (Drive access while the user is away)
            "include_granted_scopes": "true",
            # Google only issues a refresh token on consent, so force it when we need one.
            "prompt": "consent" if force_consent else "select_account",
        }
        return f"{AUTH_ENDPOINT}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> GoogleTokens:
        resp = self._http.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": self._s.google_oauth_client_id,
                "client_secret": self._s.google_oauth_client_secret.get_secret_value(),
                "redirect_uri": self._s.oauth_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            raise OAuthError("exchange_failed", f"token endpoint returned {resp.status_code}")
        body = resp.json()
        if "id_token" not in body:
            raise OAuthError("exchange_failed", "token response missing id_token")
        return GoogleTokens(
            id_token=body["id_token"],
            refresh_token=body.get("refresh_token"),
            scopes=body.get("scope", ""),
        )

    def verify_id_token(self, token: str, expected_nonce: str) -> GoogleIdentity:
        try:
            # Checks signature, expiry and audience (our client id).
            claims: dict[str, Any] = google_id_token.verify_oauth2_token(
                token, google_requests.Request(), self._s.google_oauth_client_id
            )
        except ValueError as exc:
            raise OAuthError("invalid_id_token", str(exc)) from exc
        return identity_from_claims(claims, expected_nonce)

    def revoke(self, token: str) -> None:
        """Revokes the grant at Google. Raises RevokeFailed unless Google confirms it's gone."""
        try:
            resp = self._http.post(REVOKE_ENDPOINT, data={"token": token}, timeout=10)
        except httpx.HTTPError as exc:
            raise RevokeFailed(type(exc).__name__) from exc
        if resp.status_code == 200:
            return
        # 400 invalid_token: already revoked or expired, so there's no grant left to remove.
        if resp.status_code == 400 and resp.json().get("error") == "invalid_token":
            return
        raise RevokeFailed(f"revoke endpoint returned {resp.status_code}")


def identity_from_claims(claims: dict[str, Any], expected_nonce: str) -> GoogleIdentity:
    if claims.get("iss") not in ISSUERS:
        raise OAuthError("invalid_id_token", "bad issuer")
    if not secrets.compare_digest(str(claims.get("nonce", "")), expected_nonce):
        raise OAuthError("invalid_id_token", "nonce mismatch")
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise OAuthError("email_not_verified")
    return GoogleIdentity(
        sub=str(claims["sub"]),
        email=str(claims["email"]).lower(),
        name=str(claims.get("name") or claims["email"]),
        picture=claims.get("picture"),
        domain=claims.get("hd"),
    )
