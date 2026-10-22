"""Documents API router: listing, uploading, and managing indexed documents."""

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from amber import repository
from amber.ingest import settings as indexing_settings
from amber.ingest.pipeline import process_document_upload
from amber.util import drive, drive_sync
from amber.util.posthog import get_posthog_client
from amber.util.posthog_logs import posthog_log
from amber.util.security import CsrfProtected, CurrentUser, DbDep, SettingsDep

router = APIRouter(prefix="/api/documents", tags=["documents"])
log = logging.getLogger(__name__)

EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _clean_tags(raw: list[str]) -> list[str]:
    tags = (re.sub(r"[^a-z0-9-]", "-", t.strip().lower())[:32] for t in raw)
    return list(dict.fromkeys(t for t in tags if t))[:20]


def split_csv(raw: str) -> list[str]:
    return [part for part in (p.strip() for p in raw.split(",")) if part]


def build_access(user: dict[str, Any], kind: str, emails: list[str]) -> tuple[str, list[dict[str, Any]]]:
    """Returns (documents.sharing_option, document_access grants). The owner is always granted."""
    owner = user["email"].lower()
    grants: list[dict[str, Any]] = [{"principal_type": "user", "principal_value": owner, "origin": "manual"}]
    if kind == "domain":
        if not user.get("domain"):
            raise HTTPException(status_code=400, detail="Your account has no organization domain to share with")
        grants.append({"principal_type": "domain", "principal_value": user["domain"].lower(), "origin": "manual"})
        return "domain", grants
    if kind == "people":
        clean = list(dict.fromkeys(e.strip().lower() for e in emails))
        bad = [e for e in clean if not EMAIL.match(e)]
        if bad:
            raise HTTPException(status_code=400, detail=f"Invalid email address: {bad[0]}")
        grants += [{"principal_type": "user", "principal_value": e, "origin": "manual"} for e in clean if e != owner]
        return "specific_people", grants
    return "private", grants


def _serialize(row: dict[str, Any], owner_email: str) -> dict[str, Any]:
    access = row.get("access") or []
    domain = next((a["value"] for a in access if a["type"] == "domain"), None)
    people = sorted(a["value"] for a in access if a["type"] == "user" and a["value"] != owner_email.lower())
    sharing: dict[str, Any] = {"kind": "private"}
    if domain:
        sharing = {"kind": "domain", "domain": domain}
    elif people:
        sharing = {"kind": "people", "emails": people}
    collections = row.get("collections") or []
    first_collection = collections[0] if collections else None
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "file_type": row["file_type"],
        "origin": row["origin"],
        "status": row["status"],
        "status_message": row["status_message"],
        "file_size_bytes": row["file_size_bytes"] or 0,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "last_synced_at": row["last_synced_at"].isoformat() if row.get("last_synced_at") else None,
        "chunk_count": int(row.get("chunk_count") or 0),
        "owner": {"name": row.get("owner_name"), "email": row.get("owner_email")},
        "imported_by": {"name": row.get("importer_name"), "email": row.get("importer_email")},
        "is_owner": bool(row.get("is_owner", True)),
        "drive_url": f"https://drive.google.com/file/d/{row['drive_file_id']}/view" if row["drive_file_id"] else None,
        "tags": list(row.get("tags") or []),
        "collections": [
            {"id": str(collection["id"]), "name": collection["name"]}
            for collection in collections
        ],
        "collection": first_collection["name"] if first_collection else None,
        "collection_id": str(first_collection["id"]) if first_collection else None,
        "sharing": sharing,
    }


class OrganizeRequest(BaseModel):
    collection: str | None = Field(default=None, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=20)


class AccessRequest(BaseModel):
    kind: Literal["private", "people", "domain"]
    emails: list[str] = Field(default_factory=list, max_length=100)


def apply_organization(
    conn: Any, user: dict[str, Any], document_id: uuid.UUID, *, collection: str | None, tags: list[str]
) -> None:
    repository.set_document_organization(
        conn, document_id, user["id"], collection=(collection or "").strip() or None, tags=_clean_tags(tags)
    )


def sync_access_to_drive(drive_service: Any, drive_file_id: str, access: tuple[str, list[dict[str, Any]]]) -> None:
    """Makes the file's Google Drive sharing match `access`. Raises drive.DriveSharingError."""
    grants = access[1]
    drive.sync_file_sharing(
        drive_service,
        drive_file_id,
        emails={g["principal_value"] for g in grants[1:] if g["principal_type"] == "user"},  # grants[0] is the owner
        domain=next((g["principal_value"] for g in grants if g["principal_type"] == "domain"), None),
    )


def apply_access(conn: Any, document_id: uuid.UUID, access: tuple[str, list[dict[str, Any]]]) -> None:
    sharing_option, grants = access
    repository.set_document_access(conn, document_id, grants)
    repository.set_document_sharing_option(conn, document_id, sharing_option)


@router.get("/mine")
def list_my_documents(user: CurrentUser, conn: DbDep, settings: SettingsDep) -> dict[str, Any]:
    """Documents the user can access through Drive, plus their collections and tags."""
    repository.set_app_user_context(conn, user["email"], user["domain"])
    rows = repository.list_accessible_documents(
        conn, user_id=user["id"], user_email=user["email"], user_domain=user["domain"]
    )
    drive_service = drive.build_drive_service(user["id"], conn)
    for row in rows:
        if row.get("drive_owner_email") or not row.get("drive_file_id") or drive_service is None:
            continue
        try:
            meta = (
                drive_service.files()
                .get(
                    fileId=row["drive_file_id"],
                    fields="owners(displayName, emailAddress),driveId",
                )
                .execute()
            )
            if meta.get("driveId"):
                continue
            owner = (meta.get("owners") or [None])[0] or {}
            if owner.get("emailAddress"):
                repository.update_drive_owner(
                    conn, row["id"], owner["emailAddress"], owner.get("displayName")
                )
                row["drive_owner_email"] = owner["emailAddress"].lower()
                row["drive_owner_name"] = owner.get("displayName")
                row["owner_email"] = owner["emailAddress"].lower()
                row["owner_name"] = owner.get("displayName")
                row["is_owner"] = owner["emailAddress"].lower() == user["email"].lower()
        except Exception as exc:
            log.warning("Could not refresh Drive owner for indexed file %s: %s", row["id"], type(exc).__name__)
    sync_warning = None
    if any(row.get("drive_file_id") for row in rows):
        try:
            drive_sync.ensure_drive_watch(user["id"], conn, settings)
        except drive_sync.DriveSyncError as exc:
            sync_warning = str(exc)
            log.warning("Could not ensure Drive permission sync for user %s: %s", user["id"], exc)
    sync_state = repository.get_drive_sync_state(conn, user["id"])
    conn.commit()
    return {
        "documents": [_serialize(r, r.get("owner_email") or user["email"]) for r in rows],
        "drive_sync": {
            "active": bool(sync_state and sync_state["channel_expires"] > datetime.now(UTC)),
            "expires_at": sync_state["channel_expires"].isoformat() if sync_state else None,
            "warning": sync_warning,
        },
        "collections": [
            {
                "id": str(c["id"]),
                "name": c["name"],
                "owner": {"name": c["owner_name"], "email": c["owner_email"]},
                "is_owner": c["is_owner"],
                "role": c["role"],
                "members": c["members"],
            }
            for c in repository.list_collections(conn, user["id"])
        ],
        "tags": repository.list_tag_names(conn, user["id"]),
    }


@router.get("/{document_id}/details")
def document_details(user: CurrentUser, conn: DbDep, document_id: uuid.UUID) -> dict[str, Any]:
    """Returns the cached Google Drive owner for a file the caller can access."""
    doc = _require_accessible(conn, user, document_id)
    return {
        "drive_owner": {"name": doc.get("drive_owner_name"), "email": doc.get("drive_owner_email")}
        if doc.get("drive_owner_email")
        else None
    }


def _require_owned(conn: Any, user: dict[str, Any], document_id: uuid.UUID) -> dict[str, Any]:
    doc = _require_accessible(conn, user, document_id)
    is_owner = (
        doc.get("owner_id") == user["id"]
        if not doc.get("drive_file_id")
        else (doc.get("drive_owner_email") or "").lower() == user["email"].lower()
    )
    if not is_owner:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _require_accessible(conn: Any, user: dict[str, Any], document_id: uuid.UUID) -> dict[str, Any]:
    repository.set_app_user_context(conn, user["email"], user["domain"])
    doc = repository.get_document(conn, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.put("/{document_id}/organize", dependencies=[CsrfProtected])
def organize_document(user: CurrentUser, conn: DbDep, document_id: uuid.UUID, req: OrganizeRequest) -> dict[str, Any]:
    _require_owned(conn, user, document_id)
    apply_organization(conn, user, document_id, collection=req.collection, tags=req.tags)
    conn.commit()
    client = get_posthog_client()
    if client:
        client.capture(
            "document_organized",
            properties={
                "has_collection": bool((req.collection or "").strip()),
                "tag_count": len(_clean_tags(req.tags)),
            },
        )
    return {"success": True}


@router.put("/{document_id}/access", dependencies=[CsrfProtected])
def update_document_access(user: CurrentUser, conn: DbDep, document_id: uuid.UUID, req: AccessRequest) -> dict[str, Any]:
    doc = _require_owned(conn, user, document_id)
    access = build_access(user, req.kind, req.emails)
    if doc["drive_file_id"]:
        # Drive first: if it refuses, Amber's access list stays as it was so the two never disagree.
        drive_service = drive.build_drive_service(user["id"], conn)
        if drive_service is None:
            raise HTTPException(status_code=400, detail="Google Drive isn't connected. Reconnect it to change sharing.")
        try:
            sync_access_to_drive(drive_service, doc["drive_file_id"], access)
        except drive.DriveSharingError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    apply_access(conn, document_id, access)
    repository.insert_audit(
        conn,
        actor_user_id=user["id"],
        actor_email=user["email"],
        action="update_document_access",
        target=str(document_id),
        detail={"sharing": access[0], "people": len(access[1]) - 1},
        ip=None,
    )
    conn.commit()
    client = get_posthog_client()
    if client:
        client.capture(
            "document_access_updated",
            properties={"sharing_option": access[0], "additional_member_count": len(access[1]) - 1},
        )
    return {"success": True}


@router.get("")
def list_user_documents(user: CurrentUser, conn: DbDep, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Lists documents accessible to the user."""
    # Set RLS context
    repository.set_app_user_context(conn, user["email"], user["domain"])
    docs = repository.list_documents(
        conn,
        user_id=user["id"],
        user_email=user["email"],
        user_domain=user["domain"],
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
    )
    return [dict(d) for d in docs]


@router.post("/upload", dependencies=[CsrfProtected])
def upload_document(
    user: CurrentUser,
    conn: DbDep,
    file: UploadFile = File(...),
    sharing: str = Form("private"),  # private, people, domain
    emails: str = Form(""),  # comma separated, for sharing=people
    collection: str = Form(""),
    tags: str = Form(""),  # comma separated
) -> dict[str, Any]:
    """Uploads a local file, saves to Google Drive, parses, embeds, and indexes it."""
    max_bytes = indexing_settings.load(conn).max_upload_bytes
    file_bytes = file.file.read(max_bytes + 1)  # one extra byte tells us it is over the limit without reading it all
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    if len(file_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File is larger than the {max_bytes // (1024 * 1024)} MB upload limit")

    filename = file.filename or "upload.txt"
    mime_type = file.content_type or "application/octet-stream"

    access = build_access(user, sharing, split_csv(emails))
    grants = [{"grant_type": g["principal_type"], "grantee": g["principal_value"]} for g in access[1]]

    try:
        result = process_document_upload(
            user_id=user["id"],
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
            sync_to_drive=True,
            initial_grants=grants,
        )

        # The chosen sharing wins over whatever Drive reports for a brand-new file.
        repository.set_app_user_context(conn, user["email"], user["domain"])
        document_id = uuid.UUID(result["document_id"])
        apply_access(conn, document_id, access)
        apply_organization(conn, user, document_id, collection=collection, tags=split_csv(tags))
        repository.insert_audit(
            conn,
            actor_user_id=user["id"],
            actor_email=user["email"],
            action="upload_document",
            target=filename,
            detail={"document_id": result["document_id"], "drive_file_id": result.get("drive_file_id")},
            ip=None,
        )
        conn.commit()
        client = get_posthog_client()
        if client:
            client.capture(
                "document_uploaded",
                properties={
                    "mime_type": mime_type,
                    "file_size_bytes": len(file_bytes),
                    "sharing_option": access[0],
                    "additional_member_count": len(access[1]) - 1,
                    "has_collection": bool(collection.strip()),
                    "tag_count": len(_clean_tags(split_csv(tags))),
                },
            )
        posthog_log.info(
            "Document upload completed",
            extra={
                "event": "document_upload_completed",
                "mime_type": mime_type,
                "file_size_bytes": len(file_bytes),
                "sharing_option": access[0],
                "additional_member_count": len(access[1]) - 1,
                "has_collection": bool(collection.strip()),
                "tag_count": len(_clean_tags(split_csv(tags))),
            },
        )
        return result
    except Exception as exc:
        conn.rollback()
        posthog_log.error(
            "Document upload failed",
            extra={
                "event": "document_upload_failed",
                "mime_type": mime_type,
                "file_size_bytes": len(file_bytes),
                "sharing_option": access[0],
            },
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{document_id}", dependencies=[CsrfProtected])
def delete_document_endpoint(user: CurrentUser, conn: DbDep, document_id: uuid.UUID) -> dict[str, Any]:
    """Deletes a document and its chunks."""
    doc = _require_owned(conn, user, document_id)  # only the owner can delete, however many people can see it

    repository.delete_chunks_for_document(conn, document_id)
    repository.delete_document(conn, document_id)

    repository.insert_audit(
        conn,
        actor_user_id=user["id"],
        actor_email=user["email"],
        action="delete_document",
        target=str(document_id),
        detail=None,
        ip=None,
    )
    conn.commit()
    client = get_posthog_client()
    if client:
        client.capture("document_deleted", properties={"origin": doc["origin"]})
    return {"success": True, "document_id": str(document_id)}
