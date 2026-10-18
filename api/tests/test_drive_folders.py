import pytest
from fastapi import HTTPException

from amber.api import drive as drive_api
from amber.models import DRIVE_READONLY_SCOPE, DRIVE_SCOPE
from amber.util import drive

FOLDER = drive.FOLDER_MIME
PDF = "application/pdf"
DOC = "application/vnd.google-apps.document"


class FakeFiles:
    """files().list(...).execute() over a {parent: [pages of children]} tree."""

    def __init__(self, tree):
        self.tree, self.queries = tree, []

    def list(self, q, pageToken=None, **_):
        parent = q.split("'")[1]
        self.queries.append((parent, pageToken))
        pages = self.tree.get(parent, [[]])
        index = int(pageToken or 0)
        response = {"files": pages[index]}
        if index + 1 < len(pages):
            response["nextPageToken"] = str(index + 1)
        return type("Req", (), {"execute": lambda _self: response})()


class FakeService:
    def __init__(self, tree):
        self._files = FakeFiles(tree)

    def files(self):
        return self._files


def item(id_, mime=PDF):
    return {"id": id_, "name": f"{id_}.name", "mimeType": mime}


def test_lists_subfolders_and_every_page_once():
    service = FakeService(
        {
            "root": [[item("a"), item("sub", FOLDER)], [item("b", DOC)]],
            "sub": [[item("c"), item("root", FOLDER)]],  # a folder reachable twice is listed once
        }
    )
    files, truncated = drive.list_folder_files(service, "root", limit=10)
    assert [f["id"] for f in files] == ["a", "b", "c"]
    assert truncated is False
    assert service.files().queries == [("root", None), ("root", "1"), ("sub", None)]


def test_stops_at_the_limit():
    service = FakeService({"root": [[item("a"), item("b"), item("c")]]})
    files, truncated = drive.list_folder_files(service, "root", limit=2)
    assert [f["id"] for f in files] == ["a", "b"] and truncated is True


@pytest.mark.parametrize(
    ("mime", "expected"),
    [
        (PDF, True),
        (DOC, True),
        ("text/markdown", True),
        ("application/vnd.google-apps.form", False),
        ("application/vnd.google-apps.shortcut", False),
        ("image/png", False),
    ],
)
def test_importable_types(mime, expected):
    assert drive.is_importable(mime) is expected


def test_folder_files_needs_drive_readonly(monkeypatch):
    monkeypatch.setattr(drive_api.repository, "get_token", lambda *_: {"scopes": f"openid {DRIVE_SCOPE}"})
    with pytest.raises(HTTPException) as exc:
        drive_api.list_folder_files({"id": "u"}, object(), drive_api.DriveFolderRequest(folder_ids=["root"]))
    assert exc.value.status_code == 409 and "Reconnect" in exc.value.detail


def test_folder_files_splits_importable_and_skipped(monkeypatch):
    monkeypatch.setattr(
        drive_api.repository, "get_token", lambda *_: {"scopes": f"openid {DRIVE_SCOPE} {DRIVE_READONLY_SCOPE}"}
    )
    service = FakeService({"f1": [[item("a"), item("img", "image/png")]], "f2": [[item("a"), item("b", DOC)]]})
    monkeypatch.setattr(drive_api.drive, "build_drive_service", lambda *_: service)
    result = drive_api.list_folder_files({"id": "u"}, object(), drive_api.DriveFolderRequest(folder_ids=["f1", "f2"]))
    assert [f["id"] for f in result["files"]] == ["a", "b"]  # a file in both folders is imported once
    assert result["skipped"] == ["img.name"] and result["truncated"] is False


def test_folder_files_rejects_ids_that_could_break_the_query(monkeypatch):
    monkeypatch.setattr(
        drive_api.repository, "get_token", lambda *_: {"scopes": f"{DRIVE_SCOPE} {DRIVE_READONLY_SCOPE}"}
    )
    monkeypatch.setattr(drive_api.drive, "build_drive_service", lambda *_: FakeService({}))
    with pytest.raises(HTTPException) as exc:
        drive_api.list_folder_files({"id": "u"}, object(), drive_api.DriveFolderRequest(folder_ids=["x' or '1'='1"]))
    assert exc.value.status_code == 422
