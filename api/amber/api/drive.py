"""Google Drive API router: importing files the user picked with Google's Picker."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from amber import repository
from amber.api.documents import apply_organization
from amber.ingest import settings as indexing_settings
from amber.ingest.pipeline import IndexingError, index_document_content, mark_document_failed
from amber.util import drive
from amber.util.config import get_settings
from amber.util.ratelimit import limit
from amber.util.security import CsrfProtected, CurrentUser, DbDep

log = logging.getLogger(__name__)

_picker_limit = Depends(limit("drive.picker", max_hits=30, window_seconds=60))

router = APIRouter(prefix="/api/drive", tags=["drive"])


class DriveImportRequest(BaseModel):
    file_ids: list[str]
    collection: str | None = None
    tags: list[str] = []


@router.post("/picker-token", dependencies=[CsrfProtected, _picker_limit])
def picker_token(user: CurrentUser, conn: DbDep) -> dict[str, Any]:
    """What the browser needs to open Google's file picker: a short-lived drive.file access token,
    the picker's browser API key, and the project number it uses as the app ID."""
    settings = get_settings()
    if not settings.picker_api_key or not settings.google_cloud_project_number:
        raise HTTPException(status_code=503, detail="The Google file picker isn't configured on this server")
    try:
        token, expires_in = drive.mint_picker_token(user["id"], conn)
    except drive.PickerTokenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "access_token": token,
        "expires_in": expires_in,
        "developer_key": settings.picker_api_key,
        "app_id": settings.google_cloud_project_number,
    }


@router.post("/import", dependencies=[CsrfProtected])
def import_drive_files(user: CurrentUser, conn: DbDep, req: DriveImportRequest) -> dict[str, Any]:
    """Imports files selected from Google Drive Picker, downloads content, fetches ACLs, and indexes them."""
    drive_service = drive.build_drive_service(user["id"], conn)
    if not drive_service:
        raise HTTPException(status_code=400, detail="Google Drive is not connected for this user")

    max_bytes = indexing_settings.load(conn).max_upload_bytes
    imported = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    for file_id in req.file_ids:
        title = file_id
        doc_id = None  # so a failure here never marks the previous file's document as failed
        try:
            # Get file metadata
            file_meta = (
                drive_service.files()
                .get(fileId=file_id, fields="id, name, mimeType, size, webViewLink")
                .execute()
            )
            filename = file_meta.get("name", "Untitled")
            mime_type = file_meta.get("mimeType", "application/octet-stream")

            # Google Docs, Sheets and Slides are exported to Word, Excel and PowerPoint so they parse like uploads.
            # `title` is what the user sees; `parse_name` tells the parser which format the bytes are.
            title = filename
            parse_name = filename
            file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
            if mime_type in drive.GOOGLE_EXPORTS:
                file_type, mime_type, extension = drive.GOOGLE_EXPORTS[mime_type]
                parse_name = filename + extension
                request_obj = drive_service.files().export_media(fileId=file_id, mimeType=mime_type)
            elif mime_type.startswith("application/vnd.google-apps."):
                skipped.append(filename)  # Forms, Drawings, Sites and so on have nothing to index
                continue
            else:
                request_obj = drive_service.files().get_media(fileId=file_id)

            file_bytes = request_obj.execute()
            if len(file_bytes) > max_bytes:
                raise ValueError(f"File is larger than the {max_bytes // (1024 * 1024)} MB size limit set by your admin")

            # Fetch file permissions
            grants = drive.fetch_drive_permissions(drive_service, file_id)
            if not grants:
                grants = [{"grant_type": "user", "grantee": user["email"].lower()}]

            # Process upload without re-uploading to Drive (since it's already in Drive)
            # We can invoke pipeline steps directly or via process_document_upload with sync_to_drive=False
            import hashlib

            checksum = hashlib.sha256(file_bytes).hexdigest()
            size_bytes = len(file_bytes)

            doc_row = repository.upsert_document(
                conn,
                owner_id=user["id"],
                origin="drive_sync",
                drive_file_id=file_id,
                title=title,
                file_type=file_type,
                file_size_bytes=size_bytes,
                mime_type=mime_type,
                sha256=checksum,
                status="indexing",
                sharing_option="private",
            )
            doc_id = doc_row["id"]

            repository.set_document_access(
                conn,
                doc_id,
                [
                    {
                        "principal_type": g.get("grant_type", "user"),
                        "principal_value": g.get("grantee", user["email"].lower()),
                        "origin": "drive_sync",
                    }
                    for g in grants
                ],
            )

            conn.commit()  # keep the document even if indexing fails below, so its error can be shown
            index_document_content(conn, doc_id, file_bytes, mime_type, parse_name)

            # Mark as successfully indexed
            repository.update_document_status(conn, doc_id, "indexed")
            conn.commit()

            apply_organization(conn, user, doc_id, collection=req.collection, tags=req.tags)

            imported.append({"document_id": str(doc_id), "file_id": file_id, "title": title})
        except Exception as exc:
            # One bad file shouldn't stop the rest. Keep it, flagged failed with the reason, when it got far enough
            # to have a document row; otherwise it only appears in the response.
            message = str(exc) if isinstance(exc, IndexingError) else f"Failed while importing from Google Drive: {type(exc).__name__}: {exc}"
            log.warning("Importing Drive file %s failed: %s", file_id, message)
            if doc_id:
                try:
                    mark_document_failed(conn, doc_id, message)
                except Exception:
                    conn.rollback()
            else:
                conn.rollback()
            failed.append({"title": title, "error": message})

    repository.insert_audit(
        conn,
        actor_user_id=user["id"],
        actor_email=user["email"],
        action="import_drive_files",
        target=str(req.file_ids),
        detail={"imported_count": len(imported), "failed_count": len(failed)},
        ip=None,
    )
    conn.commit()
    return {"success": True, "imported": imported, "skipped": skipped, "failed": failed}
