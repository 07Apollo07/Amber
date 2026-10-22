"""Shared constants and helpers for the auth tables (schema.sql). Rows are plain dicts."""

# Amber can read and change sharing only on files it created (uploads) and files the user picks in the
# Google Picker. This is a non-restricted scope, so the app needs no Google verification.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

# The old full-access scope still works for tokens granted before the switch; it is never requested any more.
LEGACY_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"

# Read-only access to the whole Drive, so a picked folder's files (which drive.file can't see) can be imported.
# Google treats it as a restricted scope. NOT REQUESTED ANYMORE — folder import is disabled.
# DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def can_manage_drive_sharing(scopes: str) -> bool:
    """Saving uploads and changing Drive sharing needs drive.file (or the legacy full drive scope)."""
    granted = (scopes or "").split()
    return DRIVE_SCOPE in granted or LEGACY_DRIVE_SCOPE in granted


def drive_connected(has_refresh_token: bool, scopes: str) -> bool:
    """Drive works with a stored refresh token that carries drive.file (or the legacy drive scope)."""
    return bool(has_refresh_token) and can_manage_drive_sharing(scopes)


def can_import_folders(scopes: str) -> bool:
    """Listing and reading a picked folder's files needs drive.readonly (or the legacy full drive scope).

    Returns False because drive.readonly scope is no longer requested. Folder import is disabled.
    Users can still browse folders in the Picker and multi-select files."""
    return False
