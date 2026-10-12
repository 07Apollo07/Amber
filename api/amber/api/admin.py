"""Admin API: users, every document's access settings, and indexing settings.

Admins see document metadata and who can open each file, never the text inside it."""

import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from amber import repository
from amber.ingest import settings as indexing_settings
from amber.util import audit
from amber.util.security import AdminUser, CsrfProtected, DbDep

router = APIRouter(prefix="/api/admin", tags=["admin"])

EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PUBLIC_MAIL_DOMAINS = {"gmail.com", "googlemail.com"}  # personal accounts have no organization domain


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _serialize_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "status": row["status"],
        "pending": bool(row["pending"]),
        "created_at": _iso(row["created_at"]),
        "last_login_at": _iso(row["last_login_at"]),
        "document_count": int(row["document_count"]),
    }


class NewUser(BaseModel):
    email: str = Field(max_length=320)
    name: str = Field(default="", max_length=255)
    role: str = Field(default="member", pattern="^(admin|member)$")


class UserUpdate(BaseModel):
    role: str = Field(pattern="^(admin|member)$")
    status: str = Field(pattern="^(active|deactivated)$")


def _get_user(conn: Any, user_id: uuid.UUID) -> dict[str, Any]:
    target = repository.get_user(conn, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return target


def _removes_last_admin(conn: Any, target: dict[str, Any], *, role: str, status: str) -> bool:
    """True when this change would leave the app with no active admin."""
    was_active_admin = target["role"] == "admin" and target["status"] == "active"
    still_active_admin = role == "admin" and status == "active"
    return was_active_admin and not still_active_admin and repository.count_active_admins(conn) <= 1


@router.get("/users")
def list_users(admin: AdminUser, conn: DbDep) -> dict[str, Any]:
    return {"users": [_serialize_user(r) for r in repository.list_users_with_counts(conn)]}


@router.post("/users", dependencies=[CsrfProtected])
def add_user(admin: AdminUser, conn: DbDep, request: Request, req: NewUser) -> dict[str, Any]:
    email = req.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if repository.get_user_by_email(conn, email):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    domain = email.split("@", 1)[1]
    created = repository.insert_pending_user(
        conn,
        email=email,
        name=req.name.strip() or email.split("@", 1)[0],
        domain=None if domain in PUBLIC_MAIL_DOMAINS else domain,
        role=req.role,
    )
    audit.record(conn, request, "admin.add_user", user=admin, target=email, detail={"role": req.role})
    conn.commit()
    row = next(r for r in repository.list_users_with_counts(conn) if r["id"] == created["id"])
    return {"user": _serialize_user(row)}


@router.put("/users/{user_id}", dependencies=[CsrfProtected])
def update_user(admin: AdminUser, conn: DbDep, request: Request, user_id: uuid.UUID, req: UserUpdate) -> dict[str, Any]:
    target = _get_user(conn, user_id)
    if target["id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="You can't change your own role or status")
    if _removes_last_admin(conn, target, role=req.role, status=req.status):
        raise HTTPException(status_code=400, detail="At least one active admin is required")
    repository.set_user_role_status(conn, user_id, role=req.role, status=req.status)
    audit.record(
        conn,
        request,
        "admin.update_user",
        user=admin,
        target=target["email"],
        detail={"role": req.role, "status": req.status, "was": {"role": target["role"], "status": target["status"]}},
    )
    conn.commit()
    return {"success": True}


@router.delete("/users/{user_id}", dependencies=[CsrfProtected])
def delete_user(admin: AdminUser, conn: DbDep, request: Request, user_id: uuid.UUID) -> dict[str, Any]:
    target = _get_user(conn, user_id)
    if target["id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="You can't delete your own account")
    if _removes_last_admin(conn, target, role="member", status="deactivated"):
        raise HTTPException(status_code=400, detail="At least one active admin is required")
    owned = next((r["document_count"] for r in repository.list_users_with_counts(conn) if r["id"] == user_id), 0)
    repository.delete_user(conn, user_id)
    audit.record(
        conn, request, "admin.delete_user", user=admin, target=target["email"], detail={"documents_removed": int(owned)}
    )
    conn.commit()
    return {"success": True, "documents_removed": int(owned)}


@router.get("/documents")
def list_documents(admin: AdminUser, conn: DbDep) -> dict[str, Any]:
    rows = repository.list_all_documents(conn)
    return {
        "documents": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "file_type": r["file_type"],
                "origin": r["origin"],
                "status": r["status"],
                "status_message": r["status_message"],
                "sharing_option": r["sharing_option"],
                "file_size_bytes": r["file_size_bytes"] or 0,
                "chunk_count": int(r["chunk_count"]),
                "owner": {"name": r["owner_name"], "email": r["owner_email"]},
                "drive_url": f"https://drive.google.com/file/d/{r['drive_file_id']}/view" if r["drive_file_id"] else None,
                "tags": list(r["tags"] or []),
                "access": r["access"] or [],
                "created_at": _iso(r["created_at"]),
                "updated_at": _iso(r["updated_at"]),
            }
            for r in rows
        ]
    }


class IndexingSettingsBody(BaseModel):
    chunk_size_tokens: int
    chunk_overlap_pct: int
    max_upload_mb: int


@router.get("/settings")
def get_settings_endpoint(admin: AdminUser, conn: DbDep) -> dict[str, Any]:
    cfg = indexing_settings.load(conn)
    return {"indexing": cfg.__dict__, "limits": {k: {"min": lo, "max": hi} for k, (lo, hi) in indexing_settings.LIMITS.items()}}


@router.put("/settings", dependencies=[CsrfProtected])
def update_settings(admin: AdminUser, conn: DbDep, request: Request, req: IndexingSettingsBody) -> dict[str, Any]:
    try:
        cfg = indexing_settings.validate(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    before = indexing_settings.load(conn)
    indexing_settings.save(conn, cfg, admin["id"])
    audit.record(
        conn, request, "admin.update_settings", user=admin, target=indexing_settings.KEY,
        detail={"from": before.__dict__, "to": cfg.__dict__},
    )
    conn.commit()
    return {"indexing": cfg.__dict__}
