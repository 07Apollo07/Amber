"""Admin Documents and Analytics endpoints. The repository is faked: these never touch Postgres."""

import uuid
from datetime import UTC, date, datetime

import pytest

from amber.api import admin
from amber.util.security import get_db, require_admin

ADMIN = {"id": uuid.uuid4(), "email": "admin@example.com", "role": "admin", "status": "active"}


@pytest.fixture
def admin_client(client):
    client.app.dependency_overrides[require_admin] = lambda: ADMIN
    client.app.dependency_overrides[get_db] = lambda: object()
    yield client
    client.app.dependency_overrides.clear()


def _document(index: int) -> dict:
    return {
        "id": uuid.UUID(int=index),
        "title": f"Doc {index}",
        "file_type": "pdf",
        "origin": "drive_sync",
        "status": "indexed",
        "status_message": None,
        "sharing_option": "domain",
        "drive_file_id": "abc",
        "file_size_bytes": 10,
        "created_at": datetime(2026, 10, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 2, tzinfo=UTC),
        "owner_name": "Ada",
        "owner_email": "ada@example.com",
        "importer_name": "Ada",
        "importer_email": "ada@example.com",
        "chunk_count": 4,
        "tags": ["hr"],
        "access": [{"type": "domain", "value": "example.com", "origin": "drive_sync"}],
    }


COUNTS = {"total": 60, "ready": 55, "processing": 3, "failed": 2, "from_drive": 40, "uploaded": 20, "total_bytes": 9}


def test_documents_list_filters_paginates_and_counts(admin_client, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        admin.repository,
        "list_admin_documents",
        lambda _c, **kw: calls.append(kw) or [_document(i) for i in range(kw["limit"])],
    )
    monkeypatch.setattr(admin.repository, "admin_document_counts", lambda _c: COUNTS)

    body = admin_client.get("/api/admin/documents?status=failed&origin=drive_sync&sharing=domain&q=hr").json()

    assert len(body["documents"]) == admin.PAGE_SIZE
    assert body["documents"][0]["drive_url"] == "https://drive.google.com/file/d/abc/view"
    assert body["counts"] == COUNTS
    assert body["next"]
    assert calls[0] | {"before": None} == {
        "limit": admin.PAGE_SIZE + 1,
        "before": None,
        "status_group": "failed",
        "origin": "drive_sync",
        "sharing": "domain",
        "search": "hr",
    }
    for bad in ("status=nope", "origin=nope", "sharing=public", "before=nope"):
        assert admin_client.get(f"/api/admin/documents?{bad}").status_code == 400


def test_document_detail_includes_source_usage(admin_client, monkeypatch) -> None:
    doc_id = uuid.UUID(int=3)
    monkeypatch.setattr(admin.repository, "get_admin_document", lambda _c, i: _document(3) if i == doc_id else None)
    monkeypatch.setattr(
        admin.repository,
        "document_source_usage",
        lambda _c, _i: {"answers": 7, "people": 2, "last_used": datetime(2026, 10, 18, tzinfo=UTC)},
    )

    body = admin_client.get(f"/api/admin/documents/{doc_id}").json()

    assert body["usage"] == {"answers": 7, "people": 2, "last_used": "2026-10-18T00:00:00+00:00"}
    assert "text" not in body and "content" not in body
    assert admin_client.get(f"/api/admin/documents/{uuid.uuid4()}").status_code == 404


def test_analytics_compares_windows_and_reports_success_rate(admin_client, monkeypatch) -> None:
    windows = iter(
        [
            {
                "questions": 10,
                "people": 3,
                "completed": 8,
                "failed": 2,
                "awaiting_approval": 0,
                "median_ms": 1500,
                "p95_ms": 4000,
            },
            {
                "questions": 0,
                "people": 0,
                "completed": 0,
                "failed": 0,
                "awaiting_approval": 0,
                "median_ms": None,
                "p95_ms": None,
            },
        ]
    )
    seen_tz = []
    monkeypatch.setattr(admin.repository, "trace_window_stats", lambda _c, _s, _e: next(windows))
    monkeypatch.setattr(
        admin.repository,
        "traces_per_day",
        lambda _c, _s, _e, tz: seen_tz.append(tz) or [{"day": date(2026, 10, 19), "questions": 10, "failed": 2}],
    )
    monkeypatch.setattr(
        admin.repository,
        "tool_usage",
        lambda *_a: [{"tool": "vector_search", "calls": 9, "failed": 1, "median_ms": 300}],
    )
    monkeypatch.setattr(
        admin.repository, "top_sources", lambda *_a: [{"document_id": "d1", "title": "HR", "answers": 5, "people": 2}]
    )
    monkeypatch.setattr(
        admin.repository,
        "top_askers",
        lambda *_a: [
            {"id": uuid.UUID(int=1), "email": "a@x.com", "name": "A", "questions": 10, "failed": 2, "last_asked": None}
        ],
    )
    monkeypatch.setattr(admin.repository, "admin_document_counts", lambda _c: COUNTS)
    monkeypatch.setattr(admin.repository, "recent_failed_documents", lambda _c: [])

    body = admin_client.get("/api/admin/analytics?days=7&tz=Asia/Kolkata").json()

    assert body["range"]["days"] == 7 and seen_tz == ["Asia/Kolkata"]
    assert body["current"]["success_rate"] == 0.8
    assert body["previous"]["success_rate"] is None
    assert body["per_day"] == [{"day": "2026-10-19", "questions": 10, "failed": 2}]
    assert body["tools"][0]["tool"] == "vector_search"
    assert body["library"]["failed"] == 2
    assert admin_client.get("/api/admin/analytics?days=12").status_code == 400


def test_analytics_falls_back_to_utc_for_an_unknown_time_zone(admin_client, monkeypatch) -> None:
    empty = {
        "questions": 0,
        "people": 0,
        "completed": 0,
        "failed": 0,
        "awaiting_approval": 0,
        "median_ms": None,
        "p95_ms": None,
    }
    for name in ("tool_usage", "top_sources", "top_askers"):
        monkeypatch.setattr(admin.repository, name, lambda *_a: [])
    monkeypatch.setattr(admin.repository, "trace_window_stats", lambda *_a: empty)
    monkeypatch.setattr(admin.repository, "traces_per_day", lambda *_a: [])
    monkeypatch.setattr(admin.repository, "admin_document_counts", lambda _c: {})
    monkeypatch.setattr(admin.repository, "recent_failed_documents", lambda _c: [])

    body = admin_client.get("/api/admin/analytics?tz=Mars/Olympus").json()

    assert body["range"]["tz"] == "UTC"
    assert body["library"]["total"] == 0


@pytest.mark.parametrize("path", ["/api/admin/analytics", f"/api/admin/documents/{uuid.uuid4()}"])
def test_new_admin_endpoints_reject_anonymous(client, path) -> None:
    assert client.get(path).status_code in (401, 403)
