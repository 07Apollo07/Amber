"""Row types for the auth tables (schema.sql)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"


def drive_connected(has_refresh_token: bool, scopes: str) -> bool:
    """Drive works only with a stored refresh token that carries the drive.file scope."""
    return has_refresh_token and DRIVE_FILE_SCOPE in scopes.split()


Role = Literal["admin", "member"]


@dataclass(frozen=True)
class User:
    id: uuid.UUID
    firebase_uid: str
    google_sub: str
    email: str
    domain: str | None
    name: str
    picture_url: str | None
    role: Role
    status: Literal["active", "deactivated"]
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "User":
        return cls(**row)


@dataclass(frozen=True)
class OAuthToken:
    """A user's Google refresh token, envelope-encrypted. Never stored or logged in plaintext."""

    user_id: uuid.UUID
    encrypted_refresh_token: bytes
    kms_key_version: str
    scopes: str  # space-separated, as granted by Google
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "OAuthToken":
        return cls(**(row | {"encrypted_refresh_token": bytes(row["encrypted_refresh_token"])}))

    @property
    def scope_set(self) -> set[str]:
        return set(self.scopes.split())

    @property
    def drive_connected(self) -> bool:
        return drive_connected(True, self.scopes)
