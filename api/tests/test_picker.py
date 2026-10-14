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
