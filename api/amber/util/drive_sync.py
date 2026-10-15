"""Google Drive change notifications and indexed-document ACL reconciliation."""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from amber import repository
from amber.util import drive
from amber.util.config import Settings
from amber.util.db import Connection

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
                    "address": _webhook_address(settings),
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
                    fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(id,trashed))",
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

            if change.get("removed") or file.get("trashed"):
                grants = [{"grant_type": "user", "grantee": user["email"].lower()}]
            else:
                try:
                    grants = drive.fetch_drive_permissions(service, file_id)
                except Exception as exc:
                    raise DriveSyncError(
                        f"Could not fetch permissions for Drive file {file_id}: {type(exc).__name__}"
                    ) from exc

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
            has_domain_grant = any(grant.get("grant_type") == "domain" for grant in grants)
            has_other_user = any(
                grant.get("grant_type") == "user" and grant.get("grantee") != user["email"].lower()
                for grant in grants
            )
            sharing_option = "domain" if has_domain_grant else "specific_people" if has_other_user else "private"
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
    return len(processed_files)


def validate_notification(sync_state: dict[str, Any], token: str | None, resource_id: str | None) -> bool:
    if not token or not resource_id or resource_id != sync_state["resource_id"]:
        return False
    supplied_hash = hashlib.sha256(token.encode()).hexdigest()
    return hmac.compare_digest(sync_state["token_hash"], supplied_hash)
