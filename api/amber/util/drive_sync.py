"""Google Drive change notifications and indexed-document ACL reconciliation."""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from amber import repository
from amber.ingest import pipeline
from amber.ingest import settings as indexing_settings
from amber.util import drive
from amber.util.config import Settings
from amber.util.db import Connection
from amber.util.posthog import capture_event

log = logging.getLogger(__name__)
WATCH_RENEWAL_WINDOW = timedelta(hours=24)


class DriveSyncError(Exception):
    """A Drive watch or permission reconciliation operation failed."""


def _webhook_address(settings: Settings) -> str:
    if not settings.public_origin.startswith("https://"):
        raise DriveSyncError("Google Drive notifications require AMBER_PUBLIC_BASE_URL to use HTTPS")
    return f"{settings.public_origin}/api/drive/webhook"


def ensure_drive_watch(
    user_id: uuid.UUID,
    conn: Connection,
    settings: Settings,
    *,
    force: bool = False,
) -> bool:
    """Create or renew the user's Drive watch, retaining the current cursor when renewing."""
    repository.lock_drive_sync_owner(conn, user_id)
    existing = repository.get_drive_sync_state(conn, user_id)
    now = datetime.now(UTC)
    if existing and not force and existing["channel_expires"] > now + WATCH_RENEWAL_WINDOW:
        return False

    service = drive.build_drive_service(user_id, conn)
    if service is None:
        raise DriveSyncError("Google Drive is not connected for this user")

    page_token = existing["page_token"] if existing else None
    if not page_token:
        try:
            page_token = (
                service.changes().getStartPageToken(fields="startPageToken").execute().get("startPageToken")
            )
        except Exception as exc:
            raise DriveSyncError(f"Google Drive start token request failed: {type(exc).__name__}") from exc
    if not page_token:
        raise DriveSyncError("Google Drive did not return a start page token")

    address = _webhook_address(settings)  # outside the try below, so its reason isn't hidden
    channel_id = str(uuid.uuid4())
    channel_token = secrets.token_urlsafe(32)
    try:
        response = (
            service.changes()
            .watch(
                pageToken=page_token,
                body={
                    "id": channel_id,
                    "type": "web_hook",
                    "address": address,
                    "token": channel_token,
                },
            )
            .execute()
        )
    except Exception as exc:
        raise DriveSyncError(f"Google Drive watch registration failed: {type(exc).__name__}") from exc

    resource_id = response.get("resourceId")
    expiration_ms = response.get("expiration")
    if not resource_id or not expiration_ms:
        if resource_id:
            try:
                service.channels().stop(body={"id": channel_id, "resourceId": resource_id}).execute()
            except Exception:
                log.warning("Could not stop incomplete Drive channel %s", channel_id)
        raise DriveSyncError("Google Drive returned an incomplete watch channel")

    try:
        expires_at = datetime.fromtimestamp(int(expiration_ms) / 1000, UTC)
    except (OverflowError, TypeError, ValueError) as exc:
        try:
            service.channels().stop(body={"id": channel_id, "resourceId": resource_id}).execute()
        except Exception:
            log.warning("Could not stop invalid Drive channel %s", channel_id)
        raise DriveSyncError("Google Drive returned an invalid watch expiration") from exc
    repository.save_drive_sync_state(
        conn,
        user_id=user_id,
        page_token=page_token,
        channel_id=channel_id,
        resource_id=resource_id,
        token_hash=hashlib.sha256(channel_token.encode()).hexdigest(),
        channel_expires=expires_at,
    )
    try:
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            service.channels().stop(body={"id": channel_id, "resourceId": resource_id}).execute()
        except Exception:
            log.warning("Could not stop unpersisted Drive channel %s", channel_id)
        raise

    if existing:
        try:
            service.channels().stop(
                body={"id": existing["channel_id"], "resourceId": existing["resource_id"]}
            ).execute()
        except Exception as exc:
            log.warning("Could not stop replaced Drive channel %s: %s", existing["channel_id"], type(exc).__name__)
    return True


def stop_drive_watch(user_id: uuid.UUID, conn: Connection) -> None:
    """Best-effort remote channel stop; callers remove local state in the same transaction."""
    existing = repository.get_drive_sync_state(conn, user_id)
    if not existing:
        return
    service = drive.build_drive_service(user_id, conn)
    if service is None:
        return
    try:
        service.channels().stop(
            body={"id": existing["channel_id"], "resourceId": existing["resource_id"]}
        ).execute()
    except Exception as exc:
        log.warning("Could not stop Drive channel %s: %s", existing["channel_id"], type(exc).__name__)


def process_drive_changes(conn: Connection, sync_state: dict[str, Any]) -> int:
    """Apply current Drive permissions for changed, already-indexed files before advancing the cursor."""
    user_id = sync_state["user_id"]
    user = repository.get_user(conn, user_id)
    if not user:
        raise DriveSyncError("The Drive account owner no longer exists")
    repository.set_app_user_context(conn, user["email"], user.get("domain"))
    repository.set_drive_sync_context(conn)

    service = drive.build_drive_service(user_id, conn)
    if service is None:
        raise DriveSyncError("Google Drive is not connected for this user")

    page_token = sync_state["page_token"]
    processed_files: set[str] = set()
    next_start_token: str | None = None

    while True:
        try:
            result = (
                service.changes()
                .list(
                    pageToken=page_token,
                    pageSize=1000,
                    includeRemoved=True,
                    fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(id,trashed,driveId,owners(displayName,emailAddress)))",
                )
                .execute()
            )
        except Exception as exc:
            raise DriveSyncError(f"Google Drive changes fetch failed: {type(exc).__name__}") from exc

        for change in result.get("changes", []):
            file = change.get("file") or {}
            file_id = change.get("fileId") or file.get("id")
            if not file_id or file_id in processed_files:
                continue
            processed_files.add(file_id)

            document = repository.get_document_by_drive_file_id(conn, user_id, file_id)
            if not document:
                continue

            if change.get("removed") and not file.get("trashed"):
                repository.remove_document_user_access(conn, document["id"], user["email"])
                remaining = [
                    {"grant_type": grant["principal_type"], "grantee": grant["principal_value"]}
                    for grant in repository.get_document_access(conn, document["id"])
                ]
                sharing_option = drive.sharing_option_for_grants(
                    remaining, document.get("drive_owner_email")
                )
                if sharing_option:
                    repository.set_document_sharing_option(conn, document["id"], sharing_option)
                continue
            if file.get("trashed"):
                grants = []
                repository.update_drive_owner(conn, document["id"], None, None)
            else:
                if file.get("driveId"):
                    grants = []
                    repository.update_drive_owner(conn, document["id"], None, None)
                    repository.set_document_access(conn, document["id"], [])
                    repository.set_document_sharing_option(conn, document["id"], "private")
                    continue
                try:
                    grants = drive.fetch_drive_permissions(service, file_id)
                except Exception as exc:
                    cause = exc.__cause__ or exc
                    http_status = getattr(getattr(cause, "resp", None), "status", None)
                    if http_status in (403, 404):
                        # Drive only lets editors list permissions, so a view-only or no-longer-visible
                        # file can never succeed. Keep its last known access rather than blocking the
                        # cursor (and every other file's update) behind it.
                        log.warning(
                            "Skipping permission sync for Drive file %s: HTTP %s %s",
                            file_id, http_status, type(cause).__name__,
                        )
                        continue
                    raise DriveSyncError(
                        f"Could not fetch permissions for Drive file {file_id}: {type(exc).__name__}"
                    ) from exc
                owner = (file.get("owners") or [None])[0] or {}
                owner_email = (owner.get("emailAddress") or "").lower()
                if owner_email and not any(
                    g.get("grant_type") == "user" and g.get("grantee", "").lower() == owner_email for g in grants
                ):
                    grants.append({"grant_type": "user", "grantee": owner_email})
                repository.update_drive_owner(conn, document["id"], owner_email or None, owner.get("displayName"))

            repository.set_document_access(
                conn,
                document["id"],
                [
                    {
                        "principal_type": grant["grant_type"],
                        "principal_value": grant["grantee"],
                        "origin": "drive_sync",
                    }
                    for grant in grants
                    if grant.get("grant_type") in ("user", "domain") and grant.get("grantee")
                ],
            )
            sharing_option = drive.sharing_option_for_grants(grants, document.get("drive_owner_email"))
            if sharing_option:
                repository.set_document_sharing_option(conn, document["id"], sharing_option)

        next_page_token = result.get("nextPageToken")
        if next_page_token:
            if next_page_token == page_token:
                raise DriveSyncError("Google Drive returned a repeated change page token")
            page_token = next_page_token
            continue

        next_start_token = result.get("newStartPageToken")
        if not next_start_token:
            raise DriveSyncError("Google Drive did not return a new start page token")
        break

    repository.advance_drive_sync_cursor(conn, user_id, next_start_token)
    conn.commit()
    if processed_files:
        capture_event("drive_permissions_synced", user_id, changed_file_count=len(processed_files))
    return len(processed_files)


def reindex_due_files(conn: Connection, settings: Settings, *, limit: int = 20) -> dict[str, int]:
    """Re-indexes files that haven't changed for the quiet period. Safe to run concurrently."""
    claimed = repository.claim_due_reindexes(
        conn,
        quiet_seconds=settings.drive_reindex_quiet_seconds,
        max_wait_seconds=settings.drive_reindex_max_wait_seconds,
        limit=limit,
    )
    conn.commit()  # persist the leases before the slow work

    counts = {"reindexed": 0, "unchanged": 0, "deferred": 0, "failed": 0}
    for item in claimed:
        document_id = item["document_id"]
        try:
            outcome = _reindex_one(conn, item)
        except Exception as exc:
            conn.rollback()
            log.warning("Re-indexing Drive file %s failed: %s: %s", item["drive_file_id"], type(exc).__name__, exc)
            capture_event("document_index_failed", item["user_id"], source="drive_reindex", error_type=type(exc).__name__)
            try:
                if isinstance(exc, pipeline.IndexingError):
                    repository.update_document_status(conn, document_id, "failed", status_message=str(exc)[:2000])
                repository.release_failed_reindex(conn, document_id)
                conn.commit()
            except Exception:
                conn.rollback()
            counts["failed"] += 1
            continue
        counts[outcome] += 1
    return counts


def _reindex_one(conn: Connection, item: dict[str, Any]) -> str:
    user_id = item["user_id"]
    document_id = item["document_id"]
    user = repository.get_user(conn, user_id)
    document = repository.get_document(conn, document_id)
    if not user or not document:
        repository.finish_reindex(conn, document_id, item["last_change_at"])
        conn.commit()
        return "unchanged"
    repository.set_app_user_context(conn, user["email"], user.get("domain"))

    service = drive.build_drive_service(user_id, conn)
    if service is None:
        raise DriveSyncError("Google Drive is not connected for this user")

    max_bytes = indexing_settings.load(conn).max_upload_bytes
    downloaded = drive.download_file(service, item["drive_file_id"], max_bytes)
    checksum = hashlib.sha256(downloaded["data"]).hexdigest()

    if checksum == document["sha256"]:
        # Only metadata or permissions changed, so the indexed text is still current.
        quiet = repository.finish_reindex(conn, document_id, item["last_change_at"])
        conn.commit()
        return "unchanged" if quiet else "deferred"

    repository.update_document_status(conn, document_id, "indexing")
    conn.commit()
    repository.set_app_user_context(conn, user["email"], user.get("domain"))
    chunk_count = pipeline.index_document_content(
        conn, document_id, downloaded["data"], downloaded["mime_type"], downloaded["parse_name"]
    )
    repository.update_document_content(
        conn,
        document_id,
        title=downloaded["title"],
        file_size_bytes=len(downloaded["data"]),
        sha256=checksum,
    )
    repository.update_document_status(conn, document_id, "indexed")
    repository.finish_reindex(conn, document_id, item["last_change_at"])
    conn.commit()
    capture_event(
        "document_indexed",
        user_id,
        source="drive_reindex",
        mime_type=downloaded["mime_type"],
        file_size_bytes=len(downloaded["data"]),
        chunk_count=chunk_count,
    )
    return "reindexed"


def validate_notification(sync_state: dict[str, Any], token: str | None, resource_id: str | None) -> bool:
    if not token or not resource_id or resource_id != sync_state["resource_id"]:
        return False
    supplied_hash = hashlib.sha256(token.encode()).hexdigest()
    return hmac.compare_digest(sync_state["token_hash"], supplied_hash)
