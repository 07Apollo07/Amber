import hashlib
import uuid
from datetime import UTC, datetime

from amber import repository
from amber.util import drive, drive_sync

DOC = {"id": uuid.uuid4(), "sha256": hashlib.sha256(b"old").hexdigest()}
ITEM = {
    "document_id": DOC["id"],
    "user_id": uuid.uuid4(),
    "drive_file_id": "f1",
    "last_change_at": datetime.now(UTC),
}


class Conn:
    def commit(self):
        pass

    def rollback(self):
        pass


def _patch(monkeypatch, data: bytes):
    calls = {"indexed": 0, "finished": 0}
    monkeypatch.setattr(repository, "get_user", lambda *_: {"email": "a@x.com", "domain": None})
    monkeypatch.setattr(repository, "get_document", lambda *_: DOC)
    monkeypatch.setattr(repository, "set_app_user_context", lambda *_: None)
    monkeypatch.setattr(repository, "update_document_status", lambda *_a, **_k: None)
    monkeypatch.setattr(repository, "update_document_content", lambda *_a, **_k: None)
    monkeypatch.setattr(repository, "finish_reindex", lambda *_: calls.__setitem__("finished", calls["finished"] + 1) or True)
    monkeypatch.setattr(drive, "build_drive_service", lambda *_: object())
    monkeypatch.setattr(
        drive,
        "download_file",
        lambda *_: {"title": "t", "mime_type": "text/plain", "parse_name": "t.txt", "data": data, "file_type": "txt"},
    )
    monkeypatch.setattr(drive_sync.indexing_settings, "load", lambda _c: type("S", (), {"max_upload_bytes": 10**6})())
    monkeypatch.setattr(
        drive_sync.pipeline, "index_document_content", lambda *_: calls.__setitem__("indexed", calls["indexed"] + 1)
    )
    return calls


def test_unchanged_content_is_not_reindexed(monkeypatch):
    calls = _patch(monkeypatch, b"old")
    assert drive_sync._reindex_one(Conn(), ITEM) == "unchanged"
    assert calls["indexed"] == 0 and calls["finished"] == 1


def test_changed_content_is_reindexed(monkeypatch):
    calls = _patch(monkeypatch, b"new")
    assert drive_sync._reindex_one(Conn(), ITEM) == "reindexed"
    assert calls["indexed"] == 1 and calls["finished"] == 1


def test_failure_releases_lease_and_counts(monkeypatch):
    _patch(monkeypatch, b"new")
    released = []
    monkeypatch.setattr(repository, "claim_due_reindexes", lambda *_a, **_k: [ITEM])
    monkeypatch.setattr(repository, "release_failed_reindex", lambda _c, d: released.append(d))
    monkeypatch.setattr(drive_sync.pipeline, "index_document_content", lambda *_: 1 / 0)

    class S:
        drive_reindex_quiet_seconds = 300
        drive_reindex_max_wait_seconds = 3600

    assert drive_sync.reindex_due_files(Conn(), S())["failed"] == 1
    assert released == [DOC["id"]]



def test_search_always_filters_by_access_list(monkeypatch):
    seen = {}
    monkeypatch.setattr(repository, "set_app_user_context", lambda *_: None)
    monkeypatch.setattr(repository, "fetch_all", lambda _c, sql, params: seen.update(sql=sql, params=params) or [])

    for kwargs in ({"query_text": "q"}, {"query_embedding": [0.1]}, {"query_embedding": [0.1], "query_text": "q"}, {}):
        repository.hybrid_search_chunks(Conn(), "A@X.com", None, **kwargs)
        assert "FROM document_access da" in seen["sql"] and seen["sql"].count("WHERE EXISTS") == 1
        assert seen["params"]["acl_email"] == "a@x.com" and seen["params"]["acl_domain"] is None
