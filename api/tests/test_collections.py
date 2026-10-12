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

    with pytest.raises(DriveSharingError, match="Sign in again"):
        sync_file_sharing(Denied([]), "f1", emails=set(), domain=None)
