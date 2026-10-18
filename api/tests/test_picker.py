import pytest

from amber.api import drive as drive_api
from amber.models import DRIVE_SCOPE
from amber.util import drive


class FakeCreds:
    refresh_token, token_uri, client_id, client_secret = "r", "u", "c", "s"


@pytest.mark.parametrize("path,method", [("/api/drive/picker-token", "post"), ("/api/drive/files", "get")])
def test_picker_endpoints(client, path, method):
    response = getattr(client, method)(path)
    # picker-token needs a session (and CSRF); the old browsing endpoint no longer exists
    assert response.status_code in ((401, 403) if method == "post" else (404, 405))


def test_token_is_narrowed_to_drive_file(monkeypatch):
    seen = {}

    class Narrowed:
        token, expiry = "tok", None

        def __init__(self, **kw):
            seen.update(kw)
            self.refresh_token = kw["refresh_token"]

        def refresh(self, request):
            pass

    monkeypatch.setattr(drive, "get_drive_credentials", lambda *_: FakeCreds())
    monkeypatch.setattr(drive, "Credentials", Narrowed)
    token, seconds = drive.mint_picker_token("u", object())
    assert token == "tok" and seconds >= 60
    assert seen["scopes"] == [DRIVE_SCOPE]  # even if the stored grant was broader


def test_drive_credentials_do_not_request_stored_scopes_on_refresh(monkeypatch, settings):
    monkeypatch.setattr(drive, "get_settings", lambda: settings)
    monkeypatch.setattr(
        drive.repository,
        "get_token",
        lambda *_: {
            "encrypted_refresh_token": b"encrypted",
            "scopes": f"openid email profile {DRIVE_SCOPE}",
        },
    )
    monkeypatch.setattr(drive, "decrypt_token", lambda *_args, **_kwargs: "refresh-token")

    credentials = drive.get_drive_credentials("user-id", object())

    assert credentials is not None
    assert credentials.refresh_token == "refresh-token"
    assert credentials.scopes is None


def test_not_connected_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(drive, "get_drive_credentials", lambda *_: None)
    with pytest.raises(drive.PickerTokenError):
        drive.mint_picker_token("u", object())


def test_refresh_failure_asks_to_reconnect(monkeypatch):
    from google.auth.exceptions import RefreshError

    class Broken:
        def __init__(self, **kw):
            self.refresh_token = "r"

        def refresh(self, request):
            raise RefreshError("invalid_grant")

    monkeypatch.setattr(drive, "get_drive_credentials", lambda *_: FakeCreds())
    monkeypatch.setattr(drive, "Credentials", Broken)
    with pytest.raises(drive.PickerTokenError, match="Reconnect"):
        drive.mint_picker_token("u", object())


def test_endpoint_needs_configuration():
    from fastapi import HTTPException

    class NoKey:
        picker_api_key = ""
        google_cloud_project_number = ""

    original = drive_api.get_settings
    drive_api.get_settings = lambda: NoKey()
    try:
        with pytest.raises(HTTPException) as exc:
            drive_api.picker_token({"id": "u"}, object())
        assert exc.value.status_code == 503
    finally:
        drive_api.get_settings = original


def test_drive_credentials_can_be_narrowed(monkeypatch, settings):
    """The agent asks for drive.file only, so a drive.readonly grant never lets it browse the whole Drive."""
    monkeypatch.setattr(drive, "get_settings", lambda: settings)
    monkeypatch.setattr(drive.repository, "get_token", lambda *_: {"encrypted_refresh_token": b"e", "scopes": ""})
    monkeypatch.setattr(drive, "decrypt_token", lambda *_args, **_kwargs: "refresh-token")
    assert drive.get_drive_credentials("user-id", object(), scopes=[DRIVE_SCOPE]).scopes == [DRIVE_SCOPE]
