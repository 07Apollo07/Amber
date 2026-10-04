"""Google Drive integration utilities: credential creation, folder management, file upload, and permission syncing."""

import io
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from amber import repository
from amber.util.config import get_settings
from amber.util.crypto import decrypt_token


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
