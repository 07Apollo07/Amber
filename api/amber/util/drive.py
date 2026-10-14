"""Google Drive integration utilities: credential creation, folder management, file upload, and permission syncing."""

import io
from datetime import datetime
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from amber import repository
from amber.models import DRIVE_SCOPE
from amber.util.config import get_settings
from amber.util.crypto import decrypt_token


# Google-native files have no bytes of their own, so they're exported to an Office format that our
# parsers read. Value: (file_type stored in Amber, export mime type, extension used for parsing).
GOOGLE_EXPORTS: dict[str, tuple[str, str, str]] = {
    "application/vnd.google-apps.document": (
        "gdoc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "gsheet",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "gslides",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}


def get_drive_credentials(user_id: Any, conn: Any) -> Credentials | None:
    settings = get_settings()
    token_row = repository.get_token(conn, user_id)
    if not token_row:
        return None

    try:
        refresh_token = decrypt_token(settings, token_row["encrypted_refresh_token"], str(user_id))
    except Exception:
        return None

    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret.get_secret_value()

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=token_row["scopes"].split() if token_row["scopes"] else [],
    )


class PickerTokenError(Exception):
    """The user's Drive connection can't produce a picker token. The message is safe to show."""


def mint_picker_token(user_id: Any, conn: Any) -> tuple[str, int]:
    """Returns (access_token, seconds_valid) limited to drive.file, for Google's browser-side Picker.

    Only an access token ever leaves the server, never the refresh token. The scope is narrowed
    explicitly, so a user who granted the old full-drive scope still gets a drive.file token."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request

    creds = get_drive_credentials(user_id, conn)
    if creds is None:
        raise PickerTokenError("Google Drive isn't connected. Reconnect it to pick files.")
    narrowed = Credentials(
        token=None,
        refresh_token=creds.refresh_token,
        token_uri=creds.token_uri,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        scopes=[DRIVE_SCOPE],
    )
    try:
        narrowed.refresh(Request())
    except RefreshError as exc:
        raise PickerTokenError("Google no longer accepts your Drive connection. Reconnect it to pick files.") from exc
    except Exception as exc:
        raise PickerTokenError("Couldn't reach Google to start the file picker. Try again.") from exc
    seconds = int((narrowed.expiry - datetime.utcnow()).total_seconds()) if narrowed.expiry else 3000
    return narrowed.token, max(seconds, 60)


def build_drive_service(user_id: Any, conn: Any) -> Any | None:
    creds = get_drive_credentials(user_id, conn)
    if not creds:
        return None
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_or_create_amber_uploads_folder(drive_service: Any) -> str:
    """Finds or creates the 'Amber Uploads' folder in Google Drive."""
    query = "name = 'Amber Uploads' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    response = drive_service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = response.get("files", [])
    if files:
        return files[0]["id"]

    folder_metadata = {
        "name": "Amber Uploads",
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = drive_service.files().create(body=folder_metadata, fields="id").execute()
    return folder.get("id")


def upload_file_to_drive(
    drive_service: Any,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    folder_id: str | None = None,
) -> dict[str, Any]:
    """Uploads a file to Google Drive (into Amber Uploads folder by default) and returns file metadata."""
    if not folder_id:
        folder_id = get_or_create_amber_uploads_folder(drive_service)

    file_metadata = {
        "name": filename,
        "parents": [folder_id],
    }
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    file = (
        drive_service.files()
        .create(body=file_metadata, media_body=media, fields="id, name, webViewLink, mimeType, size")
        .execute()
    )
    return file


def fetch_drive_permissions(drive_service: Any, file_id: str) -> list[dict[str, Any]]:
    """Fetches Drive file permissions and maps them to Amber document_access grants."""
    try:
        response = (
            drive_service.permissions()
            .list(fileId=file_id, fields="permissions(id, role, type, emailAddress, domain)")
            .execute()
        )
        raw_perms = response.get("permissions", [])
    except Exception:
        raw_perms = []

    grants = []
    for p in raw_perms:
        ptype = p.get("type")
        role = p.get("role")
        if role not in ("reader", "commenter", "writer", "owner"):
            continue

        if ptype == "user":
            email = p.get("emailAddress")
            if email:
                grants.append({"grant_type": "user", "grantee": email.lower()})
        elif ptype == "domain":
            domain = p.get("domain")
            if domain:
                grants.append({"grant_type": "domain", "grantee": domain.lower()})
        elif ptype == "anyone":
            grants.append({"grant_type": "public", "grantee": None})
        # Group entries or others are conservatively ignored per spec.

    return grants


class DriveSharingError(Exception):
    """A Drive permission change failed. The message is safe to show the user."""


def _drive_error_message(exc: Exception, subject: str) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    detail = str(exc)
    if status == 403 and "insufficient" in detail.lower():
        return "Amber doesn't have permission to change sharing in Google Drive yet. Sign in again and allow full Drive access."
    if status in (403, 404):
        return f"You can't change sharing for this file in Google Drive{subject}. Only people with edit access to it can."
    if status == 400 and "no google account" in detail.lower():
        return f"Google Drive can't share with {subject} because that address has no Google account."
    return f"Google Drive rejected the sharing change{subject}."


def sync_file_sharing(
    drive_service: Any,
    file_id: str,
    *,
    emails: set[str],
    domain: str | None,
) -> None:
    """Makes the file's Drive sharing match: viewers are exactly `emails` plus `domain` (if given).

    Adds missing people as viewers without sending an email, and removes people and domains that are no
    longer listed. The file owner is never touched. Link sharing ("anyone") and groups are left as they are.
    Raises DriveSharingError with a user-safe message on failure."""
    wanted = {e.lower() for e in emails}
    wanted_domain = domain.lower() if domain else None
    try:
        existing = (
            drive_service.permissions()
            .list(fileId=file_id, fields="permissions(id, role, type, emailAddress, domain)")
            .execute()
            .get("permissions", [])
        )
    except Exception as exc:
        raise DriveSharingError(_drive_error_message(exc, "")) from exc

    have_users: set[str] = set()
    have_domain = False
    to_remove: list[str] = []
    for perm in existing:
        if perm.get("role") == "owner":
            continue
        if perm.get("type") == "user":
            email = (perm.get("emailAddress") or "").lower()
            have_users.add(email)
            if email not in wanted:
                to_remove.append(perm["id"])
        elif perm.get("type") == "domain":
            if (perm.get("domain") or "").lower() == wanted_domain:
                have_domain = True
            else:
                to_remove.append(perm["id"])

    for email in sorted(wanted - have_users):
        try:
            drive_service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": "reader", "emailAddress": email},
                sendNotificationEmail=False,
                fields="id",
            ).execute()
        except Exception as exc:
            raise DriveSharingError(_drive_error_message(exc, email)) from exc

    if wanted_domain and not have_domain:
        try:
            drive_service.permissions().create(
                fileId=file_id,
                body={"type": "domain", "role": "reader", "domain": wanted_domain},
                fields="id",
            ).execute()
        except Exception as exc:
            raise DriveSharingError(_drive_error_message(exc, f" with {wanted_domain}")) from exc

    for permission_id in to_remove:
        try:
            drive_service.permissions().delete(fileId=file_id, permissionId=permission_id).execute()
        except Exception as exc:
            raise DriveSharingError(_drive_error_message(exc, "")) from exc
