"""Shared constants and helpers for the auth tables (schema.sql). Rows are plain dicts."""

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def drive_connected(has_refresh_token: bool, scopes: str) -> bool:
    """Drive works with a stored refresh token that carries the drive.readonly or drive scope."""
    if not has_refresh_token or not scopes:
        return False
    scope_list = scopes.split()
    allowed = {
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive",
    }
    return any(s in allowed for s in scope_list)
