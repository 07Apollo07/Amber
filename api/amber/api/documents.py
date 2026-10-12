"""Documents API router: listing, uploading, and managing indexed documents."""

import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from amber import repository
from amber.ingest.pipeline import process_document_upload
from amber.util import drive
from amber.util.security import CsrfProtected, CurrentUser, DbDep

router = APIRouter(prefix="/api/documents", tags=["documents"])

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
        "is_owner": bool(row.get("is_owner", True)),
        "drive_url": f"https://drive.google.com/file/d/{row['drive_file_id']}/view" if row["drive_file_id"] else None,
        "tags": list(row.get("tags") or []),
        "collection": row.get("collection"),
        "collection_id": str(row["collection_id"]) if row.get("collection_id") else None,
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
def list_my_documents(user: CurrentUser, conn: DbDep) -> dict[str, Any]:
    """Everything the user owns or has been given access to, plus the collection and tag names they can pick from."""
    repository.set_app_user_context(conn, user["email"], user["domain"])
    rows = repository.list_accessible_documents(
        conn, user_id=user["id"], user_email=user["email"], user_domain=user["domain"]
    )
    return {
        "documents": [_serialize(r, r.get("owner_email") or user["email"]) for r in rows],
        "collections": [{"id": str(c["id"]), "name": c["name"]} for c in repository.list_collections(conn, user["id"])],
        "tags": repository.list_tag_names(conn, user["id"]),
    }


@router.get("/{document_id}/details")
def document_details(user: CurrentUser, conn: DbDep, document_id: uuid.UUID) -> dict[str, Any]:
    """Details that need Google Drive: who owns the file there. `drive_owner` is null when Drive can't say."""
    doc = _require_owned(conn, user, document_id)
    drive_owner = None
    if doc["drive_file_id"]:
        drive_service = drive.build_drive_service(user["id"], conn)
        if drive_service is not None:
            try:
                meta = drive_service.files().get(fileId=doc["drive_file_id"], fields="owners(displayName, emailAddress)").execute()
                owner = (meta.get("owners") or [None])[0]
                if owner:
                    drive_owner = {"name": owner.get("displayName"), "email": owner.get("emailAddress")}
            except Exception:
                drive_owner = None  # deleted, no access, or Drive is unavailable: the page falls back to the Amber owner
    return {"drive_owner": drive_owner}


def _require_owned(conn: Any, user: dict[str, Any], document_id: uuid.UUID) -> dict[str, Any]:
    repository.set_app_user_context(conn, user["email"], user["domain"])
    doc = repository.get_document(conn, document_id)
    if not doc or doc["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.put("/{document_id}/organize", dependencies=[CsrfProtected])
def organize_document(user: CurrentUser, conn: DbDep, document_id: uuid.UUID, req: OrganizeRequest) -> dict[str, Any]:
    _require_owned(conn, user, document_id)
    apply_organization(conn, user, document_id, collection=req.collection, tags=req.tags)
    conn.commit()
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
    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

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
        return result
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{document_id}", dependencies=[CsrfProtected])
def delete_document_endpoint(user: CurrentUser, conn: DbDep, document_id: uuid.UUID) -> dict[str, Any]:
    """Deletes a document and its chunks."""
    _require_owned(conn, user, document_id)  # only the owner can delete, however many people can see it

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
    return {"success": True, "document_id": str(document_id)}
