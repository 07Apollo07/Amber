import pytest

from amber.api import admin
from amber.ingest import settings as indexing_settings
from amber.ingest.chunker import chunk_document_blocks

ADMIN = {"id": "a", "role": "admin", "status": "active"}


def test_defaults_match_the_old_hardcoded_chunking():
    cfg = indexing_settings.IndexingSettings()
    assert (cfg.chunk_size_tokens, cfg.chunk_overlap_tokens) == (800, 120)


@pytest.mark.parametrize(
    "values",
    [
        {"chunk_size_tokens": 100, "chunk_overlap_pct": 15, "max_upload_mb": 50},
        {"chunk_size_tokens": 800, "chunk_overlap_pct": 80, "max_upload_mb": 50},
        {"chunk_size_tokens": 800, "chunk_overlap_pct": 15, "max_upload_mb": 0},
        {"chunk_size_tokens": "800", "chunk_overlap_pct": 15, "max_upload_mb": 50},
        {"chunk_size_tokens": 800, "chunk_overlap_pct": 15},
    ],
)
def test_validate_rejects_out_of_range(values):
    with pytest.raises(ValueError):
        indexing_settings.validate(values)


def test_chunk_size_setting_changes_the_chunks():
    text = " ".join(f"word{i}" for i in range(3000))
    blocks = [{"content": text, "page": 1}]
    small = chunk_document_blocks(blocks, 200, 20)
    large = chunk_document_blocks(blocks, 2000, 200)
    assert len(small) > len(large) >= 1


def test_load_falls_back_to_defaults_for_bad_stored_values(monkeypatch):
    monkeypatch.setattr(indexing_settings.repository, "get_setting", lambda conn, key: {"value": {"chunk_size_tokens": -5}})
    assert indexing_settings.load(object()) == indexing_settings.IndexingSettings()
    monkeypatch.setattr(indexing_settings.repository, "get_setting", lambda conn, key: {"value": {"max_upload_mb": 10}})
    assert indexing_settings.load(object()).max_upload_mb == 10


def test_last_admin_guard(monkeypatch):
    monkeypatch.setattr(admin.repository, "count_active_admins", lambda conn: 1)
    assert admin._removes_last_admin(None, ADMIN, role="member", status="active")
    assert admin._removes_last_admin(None, ADMIN, role="admin", status="deactivated")
    assert not admin._removes_last_admin(None, ADMIN, role="admin", status="active")
    monkeypatch.setattr(admin.repository, "count_active_admins", lambda conn: 2)
    assert not admin._removes_last_admin(None, ADMIN, role="member", status="active")


@pytest.mark.parametrize(
    "method,path",
    [("get", "/api/admin/users"), ("get", "/api/admin/documents"), ("get", "/api/admin/settings"),
     ("post", "/api/admin/users"), ("delete", "/api/admin/users/00000000-0000-0000-0000-000000000000")],
)
def test_admin_endpoints_reject_anonymous(client, method, path):
    assert getattr(client, method)(path).status_code in (401, 403)
