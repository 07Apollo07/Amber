"""Shared constants and helpers for the auth tables (schema.sql). Rows are plain dicts."""

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"


def drive_connected(has_refresh_token: bool, scopes: str) -> bool:
    """Drive works only with a stored refresh token that carries the drive.file scope."""
    return has_refresh_token and DRIVE_FILE_SCOPE in scopes.split()
