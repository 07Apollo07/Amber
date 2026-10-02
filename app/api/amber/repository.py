"""SQL for users, OAuth tokens and the audit log. Every query is parameterized."""

import uuid
from datetime import datetime
from typing import Any

import psycopg2.extras

from amber.models import OAuthToken, Role, User
from amber.util.db import Db

# ---- users ----


def get_user_by_firebase_uid(db: Db, firebase_uid: str) -> User | None:
    row = db.one("SELECT * FROM users WHERE firebase_uid = %(uid)s", {"uid": firebase_uid})
    return User.from_row(row) if row else None


def lock_user_by_google_sub(db: Db, google_sub: str) -> User | None:
    """Row-locks the user for the rest of the transaction, so concurrent sign-ins serialize."""
    row = db.one("SELECT * FROM users WHERE google_sub = %(sub)s FOR UPDATE", {"sub": google_sub})
    return User.from_row(row) if row else None


def insert_user(
    db: Db,
    *,
    firebase_uid: str,
    google_sub: str,
    email: str,
    domain: str | None,
    name: str,
    picture_url: str | None,
    role: Role,
) -> User | None:
    """Returns None if a concurrent sign-in created the same user first."""
    row = db.one(
        """
        INSERT INTO users (firebase_uid, google_sub, email, domain, name, picture_url, role)
        VALUES (%(firebase_uid)s, %(google_sub)s, %(email)s, %(domain)s, %(name)s, %(picture_url)s, %(role)s)
        ON CONFLICT (google_sub) DO NOTHING
        RETURNING *
        """,
        {
            "firebase_uid": firebase_uid,
            "google_sub": google_sub,
            "email": email,
            "domain": domain,
            "name": name,
            "picture_url": picture_url,
            "role": role,
        },
    )
    return User.from_row(row) if row else None


def update_user_profile(
    db: Db,
    user_id: uuid.UUID,
    *,
    firebase_uid: str,
    email: str,
    domain: str | None,
    name: str,
    picture_url: str | None,
    role: Role,
) -> User:
    """Profile fields follow Google on every sign-in; `role` only changes via bootstrap promotion."""
    row = db.one(
        """
        UPDATE users
           SET firebase_uid = %(firebase_uid)s, email = %(email)s, domain = %(domain)s, name = %(name)s,
               picture_url = %(picture_url)s, role = %(role)s, updated_at = now()
         WHERE id = %(id)s
        RETURNING *
        """,
        {
            "id": user_id,
            "firebase_uid": firebase_uid,
            "email": email,
            "domain": domain,
            "name": name,
            "picture_url": picture_url,
            "role": role,
        },
    )
    if row is None:
        raise LookupError(f"user {user_id} vanished mid-transaction")
    return User.from_row(row)


def touch_last_login(db: Db, user_id: uuid.UUID) -> None:
    db.execute("UPDATE users SET last_login_at = now() WHERE id = %(id)s", {"id": user_id})


# ---- OAuth tokens ----


def get_token(db: Db, user_id: uuid.UUID) -> OAuthToken | None:
    row = db.one("SELECT * FROM oauth_tokens WHERE user_id = %(id)s", {"id": user_id})
    return OAuthToken.from_row(row) if row else None


def save_token(db: Db, user_id: uuid.UUID, *, encrypted: bytes, key_version: str, scopes: str) -> None:
    db.execute(
        """
        INSERT INTO oauth_tokens (user_id, encrypted_refresh_token, kms_key_version, scopes)
        VALUES (%(id)s, %(blob)s, %(version)s, %(scopes)s)
        ON CONFLICT (user_id) DO UPDATE
           SET encrypted_refresh_token = EXCLUDED.encrypted_refresh_token,
               kms_key_version = EXCLUDED.kms_key_version,
               scopes = EXCLUDED.scopes,
               updated_at = now()
        """,
        {"id": user_id, "blob": psycopg2.Binary(encrypted), "version": key_version, "scopes": scopes},
    )


def update_token_scopes(db: Db, user_id: uuid.UUID, scopes: str) -> None:
    db.execute(
        "UPDATE oauth_tokens SET scopes = %(scopes)s, updated_at = now() WHERE user_id = %(id)s",
        {"id": user_id, "scopes": scopes},
    )


def delete_token(db: Db, user_id: uuid.UUID) -> None:
    db.execute("DELETE FROM oauth_tokens WHERE user_id = %(id)s", {"id": user_id})


# ---- signed-out sessions ----


def revoke_session(db: Db, token_hash: bytes, expires_at: datetime) -> None:
    db.execute("DELETE FROM revoked_sessions WHERE expires_at < now()")  # opportunistic cleanup
    db.execute(
        """
        INSERT INTO revoked_sessions (token_hash, expires_at) VALUES (%(hash)s, %(expires_at)s)
        ON CONFLICT (token_hash) DO NOTHING
        """,
        {"hash": psycopg2.Binary(token_hash), "expires_at": expires_at},
    )


def is_session_revoked(db: Db, token_hash: bytes) -> bool:
    row = db.one(
        "SELECT 1 AS hit FROM revoked_sessions WHERE token_hash = %(hash)s", {"hash": psycopg2.Binary(token_hash)}
    )
    return row is not None


# ---- audit log (INSERT only; the app role can't read or change it) ----


def insert_audit(
    db: Db,
    *,
    actor_user_id: uuid.UUID | None,
    actor_email: str | None,
    action: str,
    target: str | None,
    detail: dict[str, Any] | None,
    ip: str | None,
) -> None:
    db.execute(
        """
        INSERT INTO audit_log (actor_user_id, actor_email, action, target, detail, ip)
        VALUES (%(actor_user_id)s, %(actor_email)s, %(action)s, %(target)s, %(detail)s, %(ip)s)
        """,
        {
            "actor_user_id": actor_user_id,
            "actor_email": actor_email,
            "action": action,
            "target": target,
            "detail": psycopg2.extras.Json(detail) if detail is not None else None,
            "ip": ip,
        },
    )
