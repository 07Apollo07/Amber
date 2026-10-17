"""Google Drive API router: importing files the user picked with Google's Picker."""

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from amber import repository
from amber.api.documents import apply_organization
from amber.ingest import settings as indexing_settings
from amber.ingest.pipeline import IndexingError, index_document_content, mark_document_failed
from amber.util import drive, drive_sync
from amber.util.config import get_settings
from amber.util.ratelimit import limit
from amber.util.security import CsrfProtected, CurrentUser, DbDep, SettingsDep

log = logging.getLogger(__name__)

_picker_limit = Depends(limit("drive.picker", max_hits=30, window_seconds=60))
_webhook_limit = Depends(limit("drive.webhook", max_hits=300, window_seconds=60))

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
def import_drive_files(
    user: CurrentUser, conn: DbDep, req: DriveImportRequest, settings: SettingsDep
) -> dict[str, Any]:
    """Imports files selected from Google Drive Picker, downloads content, fetches ACLs, and indexes them."""
    drive_service = drive.build_drive_service(user["id"], conn)
    if not drive_service:
        raise HTTPException(status_code=400, detail="Google Drive is not connected for this user")

    try:
        drive_sync.ensure_drive_watch(user["id"], conn, get_settings())
    except drive_sync.DriveSyncError as exc:
        log.warning("Could not start Drive change notifications for user %s: %s", user["id"], exc)

    max_bytes = indexing_settings.load(conn).max_upload_bytes
    imported = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    sync_warning = None
    for file_id in req.file_ids:
        title = file_id
        doc_id = None  # so a failure here never marks the previous file's document as failed
        try:
            try:
                downloaded = drive.download_file(drive_service, file_id, max_bytes)
            except drive.UnsupportedDriveFile as unsupported:
                skipped.append(str(unsupported))  # Forms, Drawings, Sites and so on have nothing to index

            # Get file metadata
            file_meta = (
                drive_service.files()
                .get(
                    fileId=file_id,
                    fields="id, name, mimeType, size, webViewLink, driveId, owners(displayName, emailAddress)",
                )
                .execute()
            )
            filename = file_meta.get("name", "Untitled")
            mime_type = file_meta.get("mimeType", "application/octet-stream")
            drive_owner = (file_meta.get("owners") or [None])[0] or {}
            drive_owner_email = (drive_owner.get("emailAddress") or "").lower()
            drive_owner_name = drive_owner.get("displayName")
            if not drive_owner_email:
                raise ValueError("Google Drive didn't provide this file's owner, so Amber can't index it safely.")

            repository.set_drive_sync_context(conn)
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

            title = downloaded["title"]
            file_type = downloaded["file_type"]
            mime_type = downloaded["mime_type"]
            parse_name = downloaded["parse_name"]
            file_bytes = downloaded["data"]

            # Fetch file permissions
            grants = drive.fetch_drive_permissions(drive_service, file_id)
            if not any(
                grant.get("grant_type") == "user" and grant.get("grantee", "").lower() == drive_owner_email
                for grant in grants
            ):
                grants.append({"grant_type": "user", "grantee": drive_owner_email})

            # Process upload without re-uploading to Drive (since it's already in Drive)
            # We can invoke pipeline steps directly or via process_document_upload with sync_to_drive=False
            checksum = hashlib.sha256(file_bytes).hexdigest()
            size_bytes = len(file_bytes)

            doc_row = repository.upsert_document(
                conn,
                owner_id=user["id"],
                imported_by_user_id=user["id"],
                drive_owner_email=drive_owner_email,
                drive_owner_name=drive_owner_name,
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
                        "principal_value": (g.get("grantee") or "").lower(),
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

    if imported:
        try:
            drive_sync.ensure_drive_watch(user["id"], conn, settings)
        except drive_sync.DriveSyncError as exc:
            sync_warning = str(exc)
            log.warning("Could not start Drive permission sync for user %s: %s", user["id"], exc)

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
    return {
        "success": True,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "drive_sync_warning": sync_warning,
    }


@router.post("/webhook", status_code=status.HTTP_204_NO_CONTENT)
def drive_webhook(request: Request, conn: DbDep) -> Response:
    """Google notifications are hints; fetch and reconcile the authoritative changes feed."""
    channel_id = request.headers.get("X-Goog-Channel-ID")
    sync_state = repository.get_drive_sync_state_by_channel(conn, channel_id or "")
    if not sync_state or not drive_sync.validate_notification(
        sync_state,
        request.headers.get("X-Goog-Channel-Token"),
        request.headers.get("X-Goog-Resource-ID"),
    ):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        drive_sync.process_drive_changes(conn, sync_state)
    except Exception as exc:
        conn.rollback()
        log.exception("Drive notification processing failed for user %s", sync_state["user_id"])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Drive sync will be retried",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sync/reindex-due")
def reindex_due_files(request: Request, settings: SettingsDep, conn: DbDep) -> dict[str, int]:
    """Re-indexes files whose Drive changes have stopped; intended for a Cloud Scheduler request every minute."""
    secret = settings.drive_sync_admin_secret.get_secret_value()
    supplied_secret = request.headers.get("X-Amber-Drive-Sync-Secret", "")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Drive sync is not configured",
        )
    if not supplied_secret or not hmac.compare_digest(secret, supplied_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return drive_sync.reindex_due_files(conn, settings)


@router.post("/sync/renew")
def renew_drive_watches(request: Request, settings: SettingsDep, conn: DbDep) -> dict[str, int]:
    """Renew expiring watch channels; intended for a daily Cloud Scheduler request."""
    secret = settings.drive_sync_admin_secret.get_secret_value()
    supplied_secret = request.headers.get("X-Amber-Drive-Sync-Secret", "")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Drive sync renewal is not configured",
        )
    if not supplied_secret or not hmac.compare_digest(secret, supplied_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    due_users = repository.list_drive_sync_users_due_for_renewal(conn)
    renewed = 0
    failed = 0
    for row in due_users:
        try:
            renewed += int(drive_sync.ensure_drive_watch(row["user_id"], conn, settings, force=True))
        except Exception:
            conn.rollback()
            failed += 1
            log.exception("Could not renew Drive watch for user %s", row["user_id"])
    return {"renewed": renewed, "failed": failed}
