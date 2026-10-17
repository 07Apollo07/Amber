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

    # The refresh token is already bound to its granted scopes. Passing the stored
    # list here makes google-auth request it explicitly during every refresh.
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
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


class UnsupportedDriveFile(Exception):
    """A Google-native file type (Forms, Drawings, Sites...) with nothing to index."""


def download_file(drive_service: Any, file_id: str, max_bytes: int) -> dict[str, Any]:
    """Downloads a Drive file (exporting Docs, Sheets and Slides to Office formats) so it parses like an upload.
    `title` is what the user sees; `parse_name` tells the parser which format the bytes are."""
    meta = drive_service.files().get(fileId=file_id, fields="id, name, mimeType, size, webViewLink").execute()
    title = meta.get("name", "Untitled")
    mime_type = meta.get("mimeType", "application/octet-stream")
    parse_name = title
    file_type = title.rsplit(".", 1)[-1].lower() if "." in title else "unknown"
    if mime_type in GOOGLE_EXPORTS:
        file_type, mime_type, extension = GOOGLE_EXPORTS[mime_type]
        parse_name = title + extension
        request = drive_service.files().export_media(fileId=file_id, mimeType=mime_type)
    elif mime_type.startswith("application/vnd.google-apps."):
        raise UnsupportedDriveFile(title)
    else:
        request = drive_service.files().get_media(fileId=file_id)
    data = request.execute()
    if len(data) > max_bytes:
        raise ValueError(f"File is larger than the {max_bytes // (1024 * 1024)} MB size limit set by your admin")
    return {
        "title": title,
        "file_type": file_type,
        "mime_type": mime_type,
        "parse_name": parse_name,
        "data": data,
    }


def fetch_drive_permissions(drive_service: Any, file_id: str) -> list[dict[str, Any]]:
    """Fetches all pages of Drive permissions and maps supported principals to Amber grants."""
    raw_perms = []
    page_token = None
    while True:
        try:
            response = (
                drive_service.permissions()
                .list(
                    fileId=file_id,
                    pageSize=100,
                    pageToken=page_token,
                    fields="nextPageToken,permissions(id, role, type, emailAddress, domain)",
                )
                .execute()
            )
        except Exception as exc:
            raise DriveSharingError(_drive_error_message(exc, "")) from exc
        raw_perms.extend(response.get("permissions", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

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
        # Group entries are not yet resolvable to individual Amber users.

    return grants


def sharing_option_for_grants(grants: list[dict[str, Any]], owner_email: str | None) -> str | None:
    if any(grant.get("grant_type") == "domain" for grant in grants):
        return "domain"
    if not owner_email:
        return None
    owner = owner_email.lower()
    has_other_user = any(
        grant.get("grant_type") == "user" and (grant.get("grantee") or "").lower() != owner
        for grant in grants
    )
    return "specific_people" if has_other_user else "private"


def ensure_drive_permission(
    drive_service: Any, file_id: str, principal_type: str, principal_value: str, role: str = "reader"
) -> str | None:
    """Adds a direct My Drive grant if no matching permission already exists.

    Returns the permission ID only when Amber created the grant, so later collection changes
    can remove only permissions owned by this collection workflow.
    """
    page_token = None
    while True:
        try:
            response = (
                drive_service.permissions()
                .list(
                    fileId=file_id,
                    pageToken=page_token,
                    pageSize=100,
                    fields="nextPageToken,permissions(id, role, type, emailAddress, domain)",
                )
                .execute()
            )
        except Exception as exc:
            raise DriveSharingError(_drive_error_message(exc, "")) from exc
        for permission in response.get("permissions", []):
            if permission.get("type") != principal_type:
                continue
            value = (
                (permission.get("emailAddress") or "").lower()
                if principal_type == "user"
                else (permission.get("domain") or "").lower()
            )
            if value == principal_value.lower() and permission.get("role") in ("reader", "commenter", "writer", "owner"):
                return None
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    body = {"type": principal_type, "role": role}
    body["emailAddress" if principal_type == "user" else "domain"] = principal_value
    try:
        result = (
            drive_service.permissions()
            .create(
                fileId=file_id,
                body=body,
                fields="id",
                **({"sendNotificationEmail": False} if principal_type == "user" else {}),
            )
            .execute()
        )
    except Exception as exc:
        raise DriveSharingError(_drive_error_message(exc, f" to {principal_value}")) from exc
    permission_id = result.get("id")
    if not permission_id:
        raise DriveSharingError(f"Google Drive did not return a permission ID for {principal_value}.")
    return permission_id


def remove_drive_permission(drive_service: Any, file_id: str, permission_id: str) -> None:
    try:
        drive_service.permissions().delete(fileId=file_id, permissionId=permission_id).execute()
    except Exception as exc:
        if getattr(getattr(exc, "resp", None), "status", None) == 404:
            return
        raise DriveSharingError(_drive_error_message(exc, "")) from exc


class DriveSharingError(Exception):
    """A Drive permission change failed. The message is safe to show the user."""


def _drive_error_message(exc: Exception, subject: str) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    detail = str(exc)
    if status == 403 and "insufficient" in detail.lower():
        return "Amber doesn't have permission to change sharing in Google Drive. Reconnect your Google Drive account and try again."
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
