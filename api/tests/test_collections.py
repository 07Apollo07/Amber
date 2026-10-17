import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from amber.api.documents import _clean_tags, build_access, split_csv

USER = {"email": "Me@Acme.com", "domain": "acme.com"}


def test_private_grants_only_the_owner():
    option, grants = build_access(USER, "private", [])
    assert option == "private"
    assert [(g["principal_type"], g["principal_value"]) for g in grants] == [("user", "me@acme.com")]


def test_people_grants_dedupe_and_skip_the_owner():
    option, grants = build_access(USER, "people", ["a@x.com", "A@x.com", "me@acme.com"])
    assert option == "specific_people"
    assert [g["principal_value"] for g in grants] == ["me@acme.com", "a@x.com"]


def test_people_rejects_bad_email():
    with pytest.raises(HTTPException) as exc:
        build_access(USER, "people", ["not-an-email"])
    assert exc.value.status_code == 400


def test_domain_needs_a_domain():
    option, grants = build_access(USER, "domain", [])
    assert option == "domain" and grants[-1] == {"principal_type": "domain", "principal_value": "acme.com", "origin": "manual"}
    with pytest.raises(HTTPException):
        build_access({"email": "me@gmail.com", "domain": None}, "domain", [])


def test_tag_and_csv_cleaning():
    assert split_csv(" a, ,b ,") == ["a", "b"]
    assert _clean_tags(["Q3 Plan", "q3-plan", ""]) == ["q3-plan"]


@pytest.mark.parametrize(
    "method,path",
    [("post", "/api/collections"), ("put", "/api/collections/00000000-0000-0000-0000-000000000000/access")],
)
def test_collection_endpoints_reject_anonymous(client: TestClient, method: str, path: str):
    response = getattr(client, method)(path, json={"name": "x", "kind": "private"})
    assert response.status_code in (401, 403)


class FakeDrive:
    """Just enough of the Drive v3 permissions API to record what sync_file_sharing does."""

    def __init__(self, existing):
        self.existing, self.created, self.deleted = existing, [], []

    def permissions(self):
        return self

    def list(self, **_):
        return self._exec({"permissions": self.existing})

    def create(self, **kw):
        self.created.append((kw["body"], kw.get("sendNotificationEmail")))
        return self._exec({})

    def delete(self, **kw):
        self.deleted.append(kw["permissionId"])
        return self._exec({})

    @staticmethod
    def _exec(result):
        class Call:
            def execute(self_inner):
                return result

        return Call()


def test_drive_sync_adds_removes_and_leaves_the_rest():
    from amber.util.drive import sync_file_sharing

    fake = FakeDrive(
        [
            {"id": "o", "role": "owner", "type": "user", "emailAddress": "me@acme.com"},
            {"id": "keep", "role": "reader", "type": "user", "emailAddress": "Keep@x.com"},
            {"id": "drop", "role": "reader", "type": "user", "emailAddress": "drop@x.com"},
            {"id": "oldDomain", "role": "reader", "type": "domain", "domain": "old.com"},
            {"id": "link", "role": "reader", "type": "anyone"},
        ]
    )
    sync_file_sharing(fake, "f1", emails={"keep@x.com", "new@x.com"}, domain="acme.com")
    assert fake.created == [
        ({"type": "user", "role": "reader", "emailAddress": "new@x.com"}, False),  # no notification email
        ({"type": "domain", "role": "reader", "domain": "acme.com"}, None),
    ]
    assert sorted(fake.deleted) == ["drop", "oldDomain"]  # owner, kept user and link sharing are untouched


def test_drive_sync_private_removes_everyone_but_the_owner():
    from amber.util.drive import sync_file_sharing

    fake = FakeDrive(
        [
            {"id": "o", "role": "owner", "type": "user", "emailAddress": "me@acme.com"},
            {"id": "a", "role": "writer", "type": "user", "emailAddress": "a@x.com"},
        ]
    )
    sync_file_sharing(fake, "f1", emails=set(), domain=None)
    assert fake.created == [] and fake.deleted == ["a"]


def test_drive_sync_reports_permission_errors_in_plain_words():
    from amber.util.drive import DriveSharingError, sync_file_sharing

    class Denied(FakeDrive):
        def list(self, **_):
            class Call:
                def execute(self_inner):
                    err = Exception("insufficientPermissions")
                    err.resp = type("R", (), {"status": 403})()
                    raise err

            return Call()

    with pytest.raises(DriveSharingError, match="Reconnect your Google Drive account"):
        sync_file_sharing(Denied([]), "f1", emails=set(), domain=None)


def test_fetch_drive_permissions_reads_every_page_and_maps_supported_principals():
    from amber.util.drive import fetch_drive_permissions

    class PagedDrive(FakeDrive):
        def __init__(self):
            self.tokens = []

        def list(self, **kw):
            self.tokens.append(kw.get("pageToken"))
            if kw.get("pageToken") is None:
                return self._exec(
                    {
                        "permissions": [{"type": "user", "role": "reader", "emailAddress": "A@X.com"}],
                        "nextPageToken": "next",
                    }
                )
            return self._exec(
                {
                    "permissions": [
                        {"type": "domain", "role": "writer", "domain": "x.com"},
                        {"type": "group", "role": "reader", "emailAddress": "team@x.com"},
                    ]
                }
            )

    permissions = PagedDrive()
    grants = fetch_drive_permissions(permissions, "f1")

    assert permissions.tokens == [None, "next"]
    assert grants == [
        {"grant_type": "user", "grantee": "a@x.com"},
        {"grant_type": "domain", "grantee": "x.com"},
    ]


def test_fetch_drive_permissions_surfaces_api_errors():
    from amber.util.drive import DriveSharingError, fetch_drive_permissions

    class Denied(FakeDrive):
        def list(self, **_):
            class Call:
                def execute(self_inner):
                    raise RuntimeError("network unavailable")

            return Call()

    with pytest.raises(DriveSharingError, match="rejected the sharing change"):
        fetch_drive_permissions(Denied([]), "f1")


def test_collection_grants_only_create_a_permission_when_needed():
    from amber.util.drive import ensure_drive_permission

    existing = FakeDrive([{"id": "existing", "type": "user", "emailAddress": "a@x.com", "role": "reader"}])
    assert ensure_drive_permission(existing, "f1", "user", "A@X.com") is None
    assert existing.created == []

    created = FakeDrive([])
    created._exec = lambda result: type("Call", (), {"execute": lambda self: {"id": "amber-grant"}})()
    assert ensure_drive_permission(created, "f1", "user", "a@x.com") == "amber-grant"
    assert created.created == [({"type": "user", "role": "reader", "emailAddress": "a@x.com"}, False)]


def test_collection_members_normalize_email_addresses():
    from amber.api.collections import CollectionAccess, _requested_members

    members = _requested_members(CollectionAccess(kind="people", emails=["A@X.com", "a@x.com"]), "owner@x.com")
    assert members == [{"principal_type": "user", "principal_value": "a@x.com", "drive_role": "reader"}]
    assert _requested_members(CollectionAccess(kind="people", emails=["owner@x.com"]), "owner@x.com") == []


def test_drive_removal_webhook_revokes_only_the_watched_user(monkeypatch: pytest.MonkeyPatch):
    import uuid

    from amber.util import drive_sync

    user_id = uuid.uuid4()
    document_id = uuid.uuid4()
    removed: list[tuple[uuid.UUID, str]] = []

    class Changes:
        def list(self, **_):
            return FakeDrive._exec(
                {"changes": [{"fileId": "f1", "removed": True}], "newStartPageToken": "next"}
            )

    class Service:
        def changes(self):
            return Changes()

    class Connection:
        def commit(self):
            self.committed = True

    monkeypatch.setattr(drive_sync.repository, "get_user", lambda *_: {"id": user_id, "email": "a@x.com"})
    monkeypatch.setattr(drive_sync.repository, "set_app_user_context", lambda *_: None)
    monkeypatch.setattr(drive_sync.repository, "set_drive_sync_context", lambda *_: None)
    monkeypatch.setattr(drive_sync.drive, "build_drive_service", lambda *_: Service())
    monkeypatch.setattr(
        drive_sync.repository,
        "get_document_by_drive_file_id",
        lambda *_: {"id": document_id, "drive_file_id": "f1"},
    )
    monkeypatch.setattr(
        drive_sync.repository,
        "remove_document_user_access",
        lambda _conn, doc_id, email: removed.append((doc_id, email)),
    )
    monkeypatch.setattr(drive_sync.repository, "get_document_access", lambda *_: [])
    monkeypatch.setattr(drive_sync.repository, "advance_drive_sync_cursor", lambda *_: None)
    conn = Connection()

    processed = drive_sync.process_drive_changes(conn, {"user_id": user_id, "page_token": "current"})

    assert processed == 1
    assert removed == [(document_id, "a@x.com")]
    assert conn.committed


def test_drive_webhook_validates_channel_secret_before_processing(monkeypatch: pytest.MonkeyPatch):
    import hashlib
    from datetime import UTC, datetime, timedelta

    from starlette.requests import Request

    from amber.api import drive as drive_api
    from amber.util import drive_sync

    state = {
        "user_id": "user-1",
        "channel_id": "channel-1",
        "resource_id": "resource-1",
        "token_hash": hashlib.sha256(b"secret").hexdigest(),
        "channel_expires": datetime.now(UTC) + timedelta(days=3),
    }
    processed: list[str] = []
    monkeypatch.setattr(drive_api.repository, "get_drive_sync_state_by_channel", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(
        drive_sync,
        "process_drive_changes",
        lambda _conn, sync_state: processed.append(sync_state["channel_id"]),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/drive/webhook",
            "query_string": b"",
            "headers": [
                (b"x-goog-channel-id", b"channel-1"),
                (b"x-goog-resource-id", b"resource-1"),
                (b"x-goog-channel-token", b"secret"),
            ],
        }
    )

    response = drive_api.drive_webhook(request, object(), object())

    assert response.status_code == 204
    assert processed == ["channel-1"]

    invalid_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/drive/webhook",
            "query_string": b"",
            "headers": [
                (b"x-goog-channel-id", b"channel-1"),
                (b"x-goog-resource-id", b"resource-1"),
                (b"x-goog-channel-token", b"wrong"),
            ],
        }
    )
    assert drive_api.drive_webhook(invalid_request, object(), object()).status_code == 204
    assert processed == ["channel-1"]


def test_ensure_drive_watch_persists_secret_hash_and_page_cursor(monkeypatch: pytest.MonkeyPatch):
    import hashlib
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from amber.util import drive_sync

    saved: dict = {}
    calls: list[tuple[str, dict]] = []

    class Call:
        def __init__(self, result):
            self.result = result

        def execute(self):
            return self.result

    class Changes:
        def getStartPageToken(self, **_):
            return Call({"startPageToken": "start-cursor"})

        def watch(self, **kwargs):
            calls.append(("watch", kwargs))
            return Call(
                {
                    "resourceId": "resource-1",
                    "expiration": str(int((datetime.now(UTC) + timedelta(days=5)).timestamp() * 1000)),
                }
            )

    class Service:
        def changes(self):
            return Changes()

    class Connection:
        committed = False

        def commit(self):
            self.committed = True

    monkeypatch.setattr(drive_sync.repository, "lock_drive_sync_owner", lambda *_: None)
    monkeypatch.setattr(drive_sync.repository, "get_drive_sync_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(drive_sync.drive, "build_drive_service", lambda *_: Service())
    monkeypatch.setattr(
        drive_sync.repository,
        "save_drive_sync_state",
        lambda _conn, **state: saved.update(state),
    )
    conn = Connection()

    started = drive_sync.ensure_drive_watch(
        "user-1", conn, SimpleNamespace(public_origin="https://amber.example")
    )

    assert started and conn.committed
    assert saved["page_token"] == "start-cursor"
    assert saved["resource_id"] == "resource-1"
    assert len(saved["token_hash"]) == 64
    channel_body = calls[0][1]["body"]
    assert saved["token_hash"] == hashlib.sha256(channel_body["token"].encode()).hexdigest()
    assert saved["channel_id"] == channel_body["id"]


def test_serialize_includes_file_details():
    from datetime import UTC, datetime

    from amber.api.documents import _serialize

    now = datetime(2026, 10, 12, tzinfo=UTC)
    row = {
        "id": "1", "title": "t", "file_type": "pdf", "origin": "desktop_upload", "status": "failed",
        "status_message": "Failed while generating embeddings: boom", "file_size_bytes": None, "created_at": now,
        "updated_at": now, "last_synced_at": None, "drive_file_id": None, "tags": [], "collection": None,
        "chunk_count": 0, "owner_name": "Me", "owner_email": "me@acme.com", "access": [],
    }
    out = _serialize(row, "me@acme.com")
    assert out["chunk_count"] == 0 and out["owner"] == {"name": "Me", "email": "me@acme.com"}
    assert out["status_message"].startswith("Failed while") and out["updated_at"].startswith("2026-10-12")
