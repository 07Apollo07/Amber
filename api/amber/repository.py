"""SQL for users, OAuth tokens, sessions and the audit log. Every query is parameterized.

Rows come back as dicts keyed by column name.
"""

import uuid
from datetime import datetime
from typing import Any

import psycopg2.extras

from amber.util.db import Connection, execute, fetch_one

Row = dict[str, Any]

# ---- users ----


def get_user_by_firebase_uid(conn: Connection, firebase_uid: str) -> Row | None:
    row = fetch_one(conn, "SELECT * FROM users WHERE firebase_uid = %(uid)s", {"uid": firebase_uid})
    return row


def lock_user_by_google_sub(conn: Connection, google_sub: str) -> Row | None:
    """Row-locks the user for the rest of the transaction, so concurrent sign-ins serialize."""
    row = fetch_one(conn, "SELECT * FROM users WHERE google_sub = %(sub)s FOR UPDATE", {"sub": google_sub})
    return row


def insert_user(
    conn: Connection,
    *,
    firebase_uid: str,
    google_sub: str,
    email: str,
    domain: str | None,
    name: str,
    picture_url: str | None,
    role: str,
) -> Row | None:
    """Returns None if a concurrent sign-in created the same user first."""
    row = fetch_one(
        conn,
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
    return row


def update_user_profile(
    conn: Connection,
    user_id: uuid.UUID,
    *,
    firebase_uid: str,
    email: str,
    domain: str | None,
    name: str,
    picture_url: str | None,
    role: str,
) -> Row:
    """Profile fields follow Google on every sign-in; `role` only changes via bootstrap promotion."""
    row = fetch_one(
        conn,
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
    return row


def touch_last_login(conn: Connection, user_id: uuid.UUID) -> None:
    execute(conn, "UPDATE users SET last_login_at = now() WHERE id = %(id)s", {"id": user_id})


# ---- OAuth tokens ----


def get_token(conn: Connection, user_id: uuid.UUID) -> Row | None:
    row = fetch_one(conn, "SELECT * FROM oauth_tokens WHERE user_id = %(id)s", {"id": user_id})
    if row:
        row["encrypted_refresh_token"] = bytes(row["encrypted_refresh_token"])  # memoryview -> bytes
    return row


def save_token(conn: Connection, user_id: uuid.UUID, *, encrypted: bytes, key_version: str, scopes: str) -> None:
    execute(
        conn,
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


def update_token_scopes(conn: Connection, user_id: uuid.UUID, scopes: str) -> None:
    execute(
        conn,
        "UPDATE oauth_tokens SET scopes = %(scopes)s, updated_at = now() WHERE user_id = %(id)s",
        {"id": user_id, "scopes": scopes},
    )


def delete_token(conn: Connection, user_id: uuid.UUID) -> None:
    execute(conn, "DELETE FROM oauth_tokens WHERE user_id = %(id)s", {"id": user_id})


# ---- signed-out sessions ----


def revoke_session(conn: Connection, token_hash: bytes, expires_at: datetime) -> None:
    execute(conn, "DELETE FROM revoked_sessions WHERE expires_at < now()")  # opportunistic cleanup
    execute(
        conn,
        """
        INSERT INTO revoked_sessions (token_hash, expires_at) VALUES (%(hash)s, %(expires_at)s)
        ON CONFLICT (token_hash) DO NOTHING
        """,
        {"hash": psycopg2.Binary(token_hash), "expires_at": expires_at},
    )


def is_session_revoked(conn: Connection, token_hash: bytes) -> bool:
    row = fetch_one(
        conn, "SELECT 1 AS hit FROM revoked_sessions WHERE token_hash = %(hash)s", {"hash": psycopg2.Binary(token_hash)}
    )
    return row is not None


# ---- audit log (INSERT only; the app role can't read or change it) ----


def insert_audit(
    conn: Connection,
    *,
    actor_user_id: uuid.UUID | None,
    actor_email: str | None,
    action: str,
    target: str | None,
    detail: dict[str, Any] | None,
    ip: str | None,
) -> None:
    execute(
        conn,
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
