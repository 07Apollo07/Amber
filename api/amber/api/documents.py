"""Documents API router: listing, uploading, and managing indexed documents."""

import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from amber import repository
from amber.ingest.pipeline import process_document_upload
from amber.util.security import CurrentUser, DbDep

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
def list_user_documents(user: CurrentUser, conn: DbDep, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Lists documents accessible to the user."""
    # Set RLS context
    repository.set_app_user_context(conn, user["email"], user["domain"])
    docs = repository.list_documents(conn, limit=limit, offset=offset)
    return [dict(d) for d in docs]


@router.post("/upload")
def upload_document(
    user: CurrentUser,
    conn: DbDep,
    file: UploadFile = File(...),
    sharing: str = Form("private"),  # private, domain, public
) -> dict[str, Any]:
    """Uploads a local file, saves to Google Drive, parses, embeds, and indexes it."""
    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    filename = file.filename or "upload.txt"
    mime_type = file.content_type or "application/octet-stream"

    # Determine initial grants based on sharing option
    grants = []
    if sharing == "public":
        grants = [{"grant_type": "public", "grantee": None}]
    elif sharing == "domain" and user.get("domain"):
        grants = [{"grant_type": "domain", "grantee": user["domain"].lower()}]
    else:
        grants = [{"grant_type": "user", "grantee": user["email"].lower()}]

    try:
        result = process_document_upload(
            user_id=user["id"],
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
            sync_to_drive=True,
            initial_grants=grants,
        )

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


@router.delete("/{document_id}")
def delete_document_endpoint(user: CurrentUser, conn: DbDep, document_id: uuid.UUID) -> dict[str, Any]:
    """Deletes a document and its chunks."""
    repository.set_app_user_context(conn, user["email"], user["domain"])
    doc = repository.get_document(conn, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

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
