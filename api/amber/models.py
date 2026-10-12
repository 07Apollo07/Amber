"""Shared constants and helpers for the auth tables (schema.sql). Rows are plain dicts."""

# Full Drive access: Amber reads imports, saves uploads, and changes who a file is shared with.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


def can_manage_drive_sharing(scopes: str) -> bool:
    """Changing a file's Drive sharing needs the full drive scope (drive.readonly can't write)."""
    return DRIVE_SCOPE in (scopes or "").split()


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
