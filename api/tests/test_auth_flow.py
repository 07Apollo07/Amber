from urllib.parse import parse_qs, urlsplit

import pytest

from amber.api.auth import safe_return_to
from amber.models import (
    DRIVE_READONLY_SCOPE,
    DRIVE_SCOPE,
    can_import_folders,
    can_manage_drive_sharing,
    drive_connected,
)
from tests.conftest import BASE_URL, start


def test_start_redirects_to_google_with_pkce_and_drive_scope(client):
    location, params = start(client)
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert params["response_type"] == "code"
    assert params["code_challenge_method"] == "S256" and len(params["code_challenge"]) >= 43
    assert params["access_type"] == "offline"
    assert params["prompt"] == "select_account"
    assert params["redirect_uri"] == f"{BASE_URL}/api/auth/google/callback"
    assert set(params["scope"].split()) == {"openid", "email", "profile", DRIVE_SCOPE, DRIVE_READONLY_SCOPE}
    assert params["state"] and params["nonce"] and params["state"] != params["nonce"]


def test_start_sets_encrypted_lax_state_cookie(client):
    resp = client.get("/api/auth/google/start", follow_redirects=False)
    header = next(h for h in resp.headers.get_list("set-cookie") if h.startswith("__Host-amber_oauth=")).lower()
    assert "httponly" in header and "secure" in header and "samesite=lax" in header and "path=/" in header
    state = parse_qs(urlsplit(resp.headers["location"]).query)["state"][0]
    assert state not in header  # state, nonce and PKCE verifier are encrypted, not readable


def test_reconnect_forces_consent(client):
    _, params = start(client, "?reconnect=true")
    assert params["prompt"] == "consent"


@pytest.mark.parametrize("target", ["/search", "/upload", "/profile?tab=drive"])
def test_return_to_accepts_app_paths(target):
    assert safe_return_to(target) == target


@pytest.mark.parametrize(
    "target", ["//evil.com", "https://evil.com", "/\\evil.com", "/api/me", "javascript:alert(1)", "", None]
)
def test_return_to_rejects_open_redirects(target):
    assert safe_return_to(target) == "/search"


@pytest.mark.parametrize(
    ("has_token", "scopes", "expected"),
    [
        (True, f"openid {DRIVE_SCOPE}", True),
        (True, "openid https://www.googleapis.com/auth/drive.file", True),
        (True, "openid https://www.googleapis.com/auth/drive", True),  # granted before the switch to drive.file
        (True, "openid https://www.googleapis.com/auth/drive.readonly", False),
        (True, "openid", False),
        (False, f"openid {DRIVE_SCOPE}", False),
    ],
)
def test_drive_connected_needs_token_and_scope(has_token, scopes, expected):
    assert drive_connected(has_token, scopes) is expected


def test_drive_scopes():
    assert DRIVE_SCOPE.endswith("/drive.file")
    assert DRIVE_READONLY_SCOPE.endswith("/drive.readonly")
    assert can_manage_drive_sharing(DRIVE_SCOPE)
    assert not can_manage_drive_sharing("openid email")


@pytest.mark.parametrize(
    ("scopes", "expected"),
    [
        (f"openid {DRIVE_SCOPE} {DRIVE_READONLY_SCOPE}", True),
        ("openid https://www.googleapis.com/auth/drive", True),  # legacy full scope can list folders too
        (f"openid {DRIVE_SCOPE}", False),
        ("", False),
    ],
)
def test_folder_import_needs_drive_readonly(scopes, expected):
    assert can_import_folders(scopes) is expected


def test_api_security_headers(client):
    resp = client.get("/api/health")
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
