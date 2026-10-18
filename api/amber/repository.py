"""SQL for users, OAuth tokens, sessions and the audit log. Every query is parameterized.

Rows come back as dicts keyed by column name.
"""

import uuid
from datetime import datetime
from typing import Any

import psycopg2.extras

from amber.util.db import Connection, execute, fetch_all, fetch_one

Row = dict[str, Any]

# ---- users ----


def get_user(conn: Connection, user_id: uuid.UUID) -> Row | None:
    return fetch_one(conn, "SELECT * FROM users WHERE id = %(id)s", {"id": user_id})


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


def lock_drive_sync_owner(conn: Connection, user_id: uuid.UUID) -> None:
    fetch_one(conn, "SELECT id FROM users WHERE id = %(id)s FOR UPDATE", {"id": user_id})


def get_drive_sync_state(conn: Connection, user_id: uuid.UUID, *, for_update: bool = False) -> Row | None:
    lock = " FOR UPDATE" if for_update else ""
    return fetch_one(
        conn,
        f"SELECT * FROM drive_sync_state WHERE user_id = %(id)s{lock}",
        {"id": user_id},
    )


def get_drive_sync_state_by_channel(
    conn: Connection, channel_id: str, *, for_update: bool = False
) -> Row | None:
    lock = " FOR UPDATE" if for_update else ""
    return fetch_one(
        conn,
        f"SELECT * FROM drive_sync_state WHERE channel_id = %(channel_id)s{lock}",
        {"channel_id": channel_id},
    )


def save_drive_sync_state(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    page_token: str,
    channel_id: str,
    resource_id: str,
    token_hash: str,
    channel_expires: datetime,
) -> None:
    execute(
        conn,
        """
        INSERT INTO drive_sync_state
            (user_id, page_token, channel_id, resource_id, token_hash, channel_expires, updated_at)
        VALUES
            (%(user_id)s, %(page_token)s, %(channel_id)s, %(resource_id)s, %(token_hash)s, %(channel_expires)s, now())
        ON CONFLICT (user_id) DO UPDATE
           SET page_token = EXCLUDED.page_token,
               channel_id = EXCLUDED.channel_id,
               resource_id = EXCLUDED.resource_id,
               token_hash = EXCLUDED.token_hash,
               channel_expires = EXCLUDED.channel_expires,
               updated_at = now()
        """,
        {
            "user_id": user_id,
            "page_token": page_token,
            "channel_id": channel_id,
            "resource_id": resource_id,
            "token_hash": token_hash,
            "channel_expires": channel_expires,
        },
    )


def advance_drive_sync_cursor(conn: Connection, user_id: uuid.UUID, page_token: str) -> None:
    execute(
        conn,
        "UPDATE drive_sync_state SET page_token = %(page_token)s, updated_at = now() WHERE user_id = %(user_id)s",
        {"user_id": user_id, "page_token": page_token},
    )


def delete_drive_sync_state(conn: Connection, user_id: uuid.UUID) -> None:
    execute(conn, "DELETE FROM drive_sync_state WHERE user_id = %(user_id)s", {"user_id": user_id})


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


# ---- Phase 3: RLS Context & Domain Repository ----


def set_app_user_context(conn: Connection, user_email: str, user_domain: str | None) -> None:
    """Sets local transaction configuration for Row-Level Security policies."""
    execute(conn, "SELECT set_config('app.user_email', %(email)s, true)", {"email": user_email})
    execute(conn, "SELECT set_config('app.user_domain', %(domain)s, true)", {"domain": user_domain or ""})


def set_drive_sync_context(conn: Connection) -> None:
    """Allow trusted Drive imports and webhook reconciliation to access source records."""
    execute(conn, "SELECT set_config('app.drive_sync', 'true', true)")


# ---- Documents ----


def upsert_document(
    conn: Connection,
    *,
    owner_id: uuid.UUID,
    imported_by_user_id: uuid.UUID | None = None,
    drive_owner_email: str | None = None,
    drive_owner_name: str | None = None,
    origin: str,
    drive_file_id: str | None = None,
    title: str,
    file_type: str,
    file_size_bytes: int | None = None,
    mime_type: str | None = None,
    sha256: str | None = None,
    status: str = "indexed",
    status_message: str | None = None,
    sharing_option: str = "private",
) -> Row:
    """Inserts or updates a document record."""
    existing = None
    if drive_file_id:
        existing = fetch_one(
            conn,
            "SELECT id FROM documents WHERE drive_file_id = %(drive_file_id)s ORDER BY created_at LIMIT 1",
            {"drive_file_id": drive_file_id},
        )
    elif sha256:
        existing = fetch_one(
            conn,
            "SELECT id FROM documents WHERE owner_id = %(owner_id)s AND sha256 = %(sha256)s",
            {"owner_id": owner_id, "sha256": sha256},
        )

    if existing:
        row = fetch_one(
            conn,
            """
            UPDATE documents
            SET title = %(title)s,
                drive_owner_email = COALESCE(%(drive_owner_email)s, drive_owner_email),
                drive_owner_name = COALESCE(%(drive_owner_name)s, drive_owner_name),
                file_type = %(file_type)s,
                file_size_bytes = %(file_size_bytes)s,
                mime_type = %(mime_type)s,
                sha256 = %(sha256)s,
                status = %(status)s,
                status_message = %(status_message)s,
                sharing_option = %(sharing_option)s,
                updated_at = now()
            WHERE id = %(id)s
            RETURNING *
            """,
            {
                "id": existing["id"],
                "title": title,
                "drive_owner_email": drive_owner_email.lower() if drive_owner_email else None,
                "drive_owner_name": drive_owner_name,
                "file_type": file_type,
                "file_size_bytes": file_size_bytes,
                "mime_type": mime_type,
                "sha256": sha256,
                "status": status,
                "status_message": status_message,
                "sharing_option": sharing_option,
            },
        )
    else:
        row = fetch_one(
            conn,
            """
            INSERT INTO documents (
                owner_id, imported_by_user_id, drive_owner_email, drive_owner_name, origin, drive_file_id,
                title, file_type, file_size_bytes, mime_type, sha256, status, status_message, sharing_option, updated_at
            )
            VALUES (
                %(owner_id)s, %(imported_by_user_id)s, %(drive_owner_email)s, %(drive_owner_name)s, %(origin)s,
                %(drive_file_id)s, %(title)s, %(file_type)s, %(file_size_bytes)s, %(mime_type)s, %(sha256)s,
                %(status)s, %(status_message)s, %(sharing_option)s, now()
            )
            RETURNING *
            """,
            {
                "owner_id": owner_id,
                "imported_by_user_id": imported_by_user_id or owner_id,
                "drive_owner_email": drive_owner_email.lower() if drive_owner_email else None,
                "drive_owner_name": drive_owner_name,
                "origin": origin,
                "drive_file_id": drive_file_id,
                "title": title,
                "file_type": file_type,
                "file_size_bytes": file_size_bytes,
                "mime_type": mime_type,
                "sha256": sha256,
                "status": status,
                "status_message": status_message,
                "sharing_option": sharing_option,
            },
        )
    if row is None:
        raise RuntimeError("Failed to upsert document")
    return row


def get_document(conn: Connection, document_id: uuid.UUID) -> Row | None:
    return fetch_one(conn, "SELECT * FROM documents WHERE id = %(id)s", {"id": document_id})


def get_document_by_drive_file_id(conn: Connection, owner_id: uuid.UUID, drive_file_id: str) -> Row | None:
    return fetch_one(
        conn,
        "SELECT * FROM documents WHERE drive_file_id = %(drive_file_id)s ORDER BY created_at LIMIT 1",
        {"drive_file_id": drive_file_id},
    )


def get_drive_sync_state(conn: Connection, user_id: uuid.UUID) -> Row | None:
    return fetch_one(
        conn,
        "SELECT * FROM drive_sync_state WHERE user_id = %(user_id)s FOR UPDATE",
        {"user_id": user_id},
    )


def get_drive_sync_state_by_channel(conn: Connection, channel_id: str) -> Row | None:
    return fetch_one(
        conn,
        "SELECT * FROM drive_sync_state WHERE channel_id = %(channel_id)s FOR UPDATE",
        {"channel_id": channel_id},
    )


def save_drive_sync_state(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    page_token: str,
    channel_id: str,
    resource_id: str,
    token_hash: str,
    channel_expires: datetime,
) -> None:
    execute(
        conn,
        """
        INSERT INTO drive_sync_state
            (user_id, page_token, channel_id, resource_id, token_hash, channel_expires, updated_at)
        VALUES
            (%(user_id)s, %(page_token)s, %(channel_id)s, %(resource_id)s, %(token_hash)s,
             %(channel_expires)s, now())
        ON CONFLICT (user_id) DO UPDATE SET
            page_token = EXCLUDED.page_token,
            channel_id = EXCLUDED.channel_id,
            resource_id = EXCLUDED.resource_id,
            token_hash = EXCLUDED.token_hash,
            channel_expires = EXCLUDED.channel_expires,
            updated_at = now()
        """,
        {
            "user_id": user_id,
            "page_token": page_token,
            "channel_id": channel_id,
            "resource_id": resource_id,
            "token_hash": token_hash,
            "channel_expires": channel_expires,
        },
    )


def advance_drive_sync_cursor(conn: Connection, user_id: uuid.UUID, page_token: str) -> None:
    execute(
        conn,
        """
        UPDATE drive_sync_state
        SET page_token = %(page_token)s, last_synced_at = now(), updated_at = now()
        WHERE user_id = %(user_id)s
        """,
        {"user_id": user_id, "page_token": page_token},
    )


def list_drive_sync_users_due_for_renewal(conn: Connection) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT user_id FROM drive_sync_state
        WHERE channel_expires <= now() + interval '24 hours'
        ORDER BY channel_expires
        """,
    )


def delete_drive_sync_state(conn: Connection, user_id: uuid.UUID) -> None:
    execute(conn, "DELETE FROM drive_sync_state WHERE user_id = %(user_id)s", {"user_id": user_id})


def mark_drive_file_dirty(
    conn: Connection, *, document_id: uuid.UUID, user_id: uuid.UUID, drive_file_id: str
) -> None:
    """Records a change to an indexed file. Every call restarts its quiet period."""
    execute(
        conn,
        """
        INSERT INTO drive_pending_reindex (document_id, user_id, drive_file_id)
        VALUES (%(document_id)s, %(user_id)s, %(drive_file_id)s)
        ON CONFLICT (document_id) DO UPDATE SET last_change_at = now(), attempts = 0
        """,
        {"document_id": document_id, "user_id": user_id, "drive_file_id": drive_file_id},
    )


def claim_due_reindexes(
    conn: Connection, *, quiet_seconds: int, max_wait_seconds: int, limit: int, max_attempts: int = 5
) -> list[Row]:
    """Leases files whose changes have stopped for `quiet_seconds` (or that have waited `max_wait_seconds`
    since their first change). A lease lasts 15 minutes, so a crashed run is picked up again."""
    return fetch_all(
        conn,
        """
        UPDATE drive_pending_reindex p
        SET claimed_at = now()
        WHERE p.document_id IN (
            SELECT document_id FROM drive_pending_reindex
            WHERE (last_change_at <= now() - make_interval(secs => %(quiet)s)
                   OR first_change_at <= now() - make_interval(secs => %(max_wait)s))
              AND (claimed_at IS NULL OR claimed_at <= now() - interval '15 minutes')
              AND attempts < %(max_attempts)s
            ORDER BY last_change_at
            LIMIT %(limit)s
            FOR UPDATE SKIP LOCKED
        )
        RETURNING p.document_id, p.user_id, p.drive_file_id, p.last_change_at
        """,
        {"quiet": quiet_seconds, "max_wait": max_wait_seconds, "limit": limit, "max_attempts": max_attempts},
    )


def finish_reindex(conn: Connection, document_id: uuid.UUID, claimed_change_at: datetime) -> bool:
    """Removes the pending row unless the file changed again after it was claimed. In that case the row
    stays (with a fresh max-wait clock) and False is returned."""
    row = fetch_one(
        conn,
        "DELETE FROM drive_pending_reindex WHERE document_id = %(id)s AND last_change_at = %(at)s RETURNING 1 AS ok",
        {"id": document_id, "at": claimed_change_at},
    )
    if row:
        return True
    execute(
        conn,
        """
        UPDATE drive_pending_reindex SET claimed_at = NULL, first_change_at = now(), attempts = 0
        WHERE document_id = %(id)s
        """,
        {"id": document_id},
    )
    return False


def release_failed_reindex(conn: Connection, document_id: uuid.UUID) -> None:
    execute(
        conn,
        "UPDATE drive_pending_reindex SET claimed_at = NULL, attempts = attempts + 1 WHERE document_id = %(id)s",
        {"id": document_id},
    )


def update_document_content(
    conn: Connection, document_id: uuid.UUID, *, title: str, file_size_bytes: int, sha256: str
) -> None:
    execute(
        conn,
        """
        UPDATE documents SET title = %(title)s, file_size_bytes = %(size)s, sha256 = %(sha256)s, updated_at = now()
        WHERE id = %(id)s
        """,
        {"id": document_id, "title": title, "size": file_size_bytes, "sha256": sha256},
    )


def list_documents(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    user_email: str,
    user_domain: str | None,
    limit: int = 100,
    offset: int = 0,
) -> list[Row]:
    """Documents the user owns or has been granted (by email or by their domain).

    The access check is spelled out here rather than left to row-level security, which Postgres
    skips for table owners and superusers."""
    return fetch_all(
        conn,
        """
        SELECT d.* FROM documents d
         WHERE EXISTS (
                 SELECT 1 FROM document_access da
                  WHERE da.document_id = d.id
                    AND ((da.principal_type = 'user' AND da.principal_value = %(email)s)
                      OR (da.principal_type = 'domain' AND %(domain)s <> '' AND da.principal_value = %(domain)s))
               )
         ORDER BY d.created_at DESC
         LIMIT %(limit)s OFFSET %(offset)s
        """,
        {
            "user_id": user_id,
            "email": user_email.lower(),
            "domain": (user_domain or "").lower(),
            "limit": limit,
            "offset": offset,
        },
    )


def delete_document(conn: Connection, document_id: uuid.UUID) -> None:
    execute(conn, "DELETE FROM documents WHERE id = %(id)s", {"id": document_id})


def update_document_status(
    conn: Connection,
    document_id: uuid.UUID,
    status: str,
    status_message: str | None = None,
) -> Row | None:
    return fetch_one(
        conn,
        """
        UPDATE documents
        SET status = %(status)s,
            status_message = %(status_message)s,
            last_synced_at = CASE WHEN %(status)s = 'indexed' THEN now() ELSE last_synced_at END,
            updated_at = now()
        WHERE id = %(id)s
        RETURNING *
        """,
        {
            "id": document_id,
            "status": status,
            "status_message": status_message,
        },
    )


# ---- Document Access (ACL) ----


def set_document_access(conn: Connection, document_id: uuid.UUID, grants: list[dict[str, Any]]) -> None:
    """grants: list of dicts with principal_type ('user', 'domain') and principal_value (email or domain string)."""
    execute(conn, "DELETE FROM document_access WHERE document_id = %(document_id)s", {"document_id": document_id})
    for grant in grants:
        principal_type = grant.get("principal_type", grant.get("grant_type", "user"))
        principal_value = grant.get("principal_value", grant.get("grantee", ""))
        origin = grant.get("origin", "drive_sync")
        if not principal_value and principal_type == "user":
            continue
        if principal_type not in ("user", "domain"):
            continue
        execute(
            conn,
            """
            INSERT INTO document_access (document_id, principal_type, principal_value, origin)
            VALUES (%(document_id)s, %(principal_type)s, %(principal_value)s, %(origin)s)
            ON CONFLICT (document_id, principal_type, principal_value) DO NOTHING
            """,
            {
                "document_id": document_id,
                "principal_type": principal_type,
                "principal_value": principal_value,
                "origin": origin,
            },
        )


def update_drive_owner(
    conn: Connection, document_id: uuid.UUID, owner_email: str | None, owner_name: str | None
) -> None:
    execute(
        conn,
        """
        UPDATE documents
           SET drive_owner_email = %(email)s, drive_owner_name = %(name)s, updated_at = now()
         WHERE id = %(id)s
        """,
        {"id": document_id, "email": owner_email.lower() if owner_email else None, "name": owner_name},
    )


def get_document_access(conn: Connection, document_id: uuid.UUID) -> list[Row]:
    return fetch_all(
        conn, "SELECT * FROM document_access WHERE document_id = %(document_id)s", {"document_id": document_id}
    )


# ---- Chunks & Hybrid Search ----


def insert_chunk(
    conn: Connection,
    *,
    document_id: uuid.UUID,
    ord: int,
    text: str,
    page: int | None = None,
    embedding: list[float] | None = None,
) -> Row:
    # Format embedding list as pgvector string representation if present
    emb_str = str(embedding) if embedding else None
    row = fetch_one(
        conn,
        """
        INSERT INTO chunks (document_id, ord, text, page, embedding)
        VALUES (%(document_id)s, %(ord)s, %(text)s, %(page)s, %(embedding)s::vector)
        RETURNING id, document_id, ord, text AS content, page, created_at
        """,
        {
            "document_id": document_id,
            "ord": ord,
            "text": text,
            "page": page,
            "embedding": emb_str,
        },
    )
    if row is None:
        raise RuntimeError("Failed to insert chunk")
    return row


def get_chunks_for_document(conn: Connection, document_id: uuid.UUID) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT id, document_id, ord, text AS content, page, created_at FROM chunks WHERE document_id = %(document_id)s ORDER BY ord ASC",
        {"document_id": document_id},
    )


def delete_chunks_for_document(conn: Connection, document_id: uuid.UUID) -> None:
    execute(conn, "DELETE FROM chunks WHERE document_id = %(document_id)s", {"document_id": document_id})


def hybrid_search_chunks(
    conn: Connection,
    user_email: str,
    user_domain: str | None,
    query_embedding: list[float] | None = None,
    query_text: str | None = None,
    *,
    limit: int = 40,
    collection_ids: list[uuid.UUID] | None = None,
    file_types: list[str] | None = None,
) -> list[Row]:
    """Performs hybrid vector cosine + full-text search with RLS document pre-filtering."""
    set_app_user_context(conn, user_email, user_domain)

    emb_str = str(query_embedding) if query_embedding else None

    # We join chunks with documents (which enforces RLS automatically via policy)
    # and optional collection_documents / file_types filters.
    # Note: RLS on documents ensures only permitted documents are visible.

    # Let's construct a flexible query supporting vector distance and/or text ts_rank_cd.
    # If both query_embedding and query_text are provided, we can combine or use vector distance as primary order.
    # Let's use cosine distance (<=>) when embedding is provided, and/or ts_rank when query_text is provided.

    params: dict[str, Any] = {
        "limit": limit,
        "query_embedding": emb_str,
        "query_text": query_text or "",
    }

    # The access check is explicit here as well as in the RLS policy, so search stays filtered even if
    # RLS is skipped (a table-owner or superuser connection) or relaxed (app.drive_sync in this transaction).
    filters = [
        """EXISTS (
            SELECT 1 FROM document_access da
             WHERE da.document_id = d.id
               AND ((da.principal_type = 'user' AND da.principal_value = %(acl_email)s)
                    OR (da.principal_type = 'domain' AND da.principal_value = %(acl_domain)s))
        )"""
    ]
    params["acl_email"] = user_email.lower()
    params["acl_domain"] = user_domain.lower() if user_domain else None
    if collection_ids:
        filters.append(
            "d.id IN (SELECT document_id FROM collection_documents WHERE collection_id = ANY(%(collection_ids)s))"
        )
        params["collection_ids"] = collection_ids
    if file_types:
        filters.append("d.file_type = ANY(%(file_types)s)")
        params["file_types"] = file_types

    where_clause = "WHERE " + " AND ".join(filters)

    if query_embedding and query_text:
        sql = f"""
        SELECT c.id, c.document_id, c.ord, c.text AS content, c.page,
               d.title AS document_title, d.origin AS document_source, d.file_type, d.drive_file_id,
               (c.embedding <=> %(query_embedding)s::vector) AS vector_distance,
               ts_rank_cd(c.tsv, plainto_tsquery('english', %(query_text)s)) AS text_rank
          FROM chunks c
          JOIN documents d ON c.document_id = d.id
          {where_clause}
         ORDER BY (c.embedding <=> %(query_embedding)s::vector) ASC
         LIMIT %(limit)s
        """
    elif query_embedding:
        sql = f"""
        SELECT c.id, c.document_id, c.ord, c.text AS content, c.page,
               d.title AS document_title, d.origin AS document_source, d.file_type, d.drive_file_id,
               (c.embedding <=> %(query_embedding)s::vector) AS vector_distance
          FROM chunks c
          JOIN documents d ON c.document_id = d.id
          {where_clause}
         ORDER BY (c.embedding <=> %(query_embedding)s::vector) ASC
         LIMIT %(limit)s
        """
    elif query_text:
        sql = f"""
        SELECT c.id, c.document_id, c.ord, c.text AS content, c.page,
               d.title AS document_title, d.origin AS document_source, d.file_type, d.drive_file_id,
               ts_rank_cd(c.tsv, plainto_tsquery('english', %(query_text)s)) AS text_rank
          FROM chunks c
          JOIN documents d ON c.document_id = d.id
          {where_clause}
          AND c.tsv @@ plainto_tsquery('english', %(query_text)s)
         ORDER BY text_rank DESC
         LIMIT %(limit)s
        """
    else:
        sql = f"""
        SELECT c.id, c.document_id, c.ord, c.text AS content, c.page,
               d.title AS document_title, d.origin AS document_source, d.file_type, d.drive_file_id
          FROM chunks c
          JOIN documents d ON c.document_id = d.id
          {where_clause}
         ORDER BY c.created_at DESC
         LIMIT %(limit)s
        """

    return fetch_all(conn, sql, params)


def count_hidden_chunks(conn: Connection, user_email: str, user_domain: str | None, query_text: str) -> int:
    """Counts matching chunks in documents the user does NOT have access to."""
    set_app_user_context(conn, user_email, user_domain)
    # Documents accessible to user: visible via RLS
    # Hidden documents: not visible via RLS. Since RLS filters documents, we can count chunks whose document_id is NOT in the RLS-filtered documents list.
    row = fetch_one(
        conn,
        """
        SELECT count(*) AS cnt
          FROM chunks c
         WHERE c.document_id NOT IN (SELECT id FROM documents)
           AND c.tsv @@ plainto_tsquery('english', %(query_text)s)
        """,
        {"query_text": query_text},
    )
    return row["cnt"] if row else 0


# ---- Collections & Collection Documents ----


def create_collection(
    conn: Connection, *, name: str, description: str | None = None, created_by: uuid.UUID | None = None
) -> Row:
    row = fetch_one(
        conn,
        """
        INSERT INTO collections (name, description, created_by)
        VALUES (%(name)s, %(description)s, %(created_by)s)
        RETURNING *
        """,
        {"name": name, "description": description, "created_by": created_by},
    )
    if row is None:
        raise RuntimeError("Failed to create collection")
    return row


def get_collection(conn: Connection, collection_id: uuid.UUID) -> Row | None:
    return fetch_one(conn, "SELECT * FROM collections WHERE id = %(id)s", {"id": collection_id})


def list_collections(conn: Connection) -> list[Row]:
    return fetch_all(conn, "SELECT * FROM collections ORDER BY name ASC")


def update_collection(conn: Connection, collection_id: uuid.UUID, *, name: str, description: str | None = None) -> Row:
    row = fetch_one(
        conn,
        """
        UPDATE collections
           SET name = %(name)s, description = %(description)s, updated_at = now()
         WHERE id = %(id)s
        RETURNING *
        """,
        {"id": collection_id, "name": name, "description": description},
    )
    if row is None:
        raise LookupError(f"Collection {collection_id} not found")
    return row


def delete_collection(conn: Connection, collection_id: uuid.UUID) -> None:
    execute(conn, "DELETE FROM collections WHERE id = %(id)s", {"id": collection_id})


def add_document_to_collection(conn: Connection, collection_id: uuid.UUID, document_id: uuid.UUID) -> None:
    execute(
        conn,
        """
        INSERT INTO collection_documents (collection_id, document_id)
        VALUES (%(collection_id)s, %(document_id)s)
        ON CONFLICT DO NOTHING
        """,
        {"collection_id": collection_id, "document_id": document_id},
    )


def remove_document_from_collection(conn: Connection, collection_id: uuid.UUID, document_id: uuid.UUID) -> None:
    execute(
        conn,
        "DELETE FROM collection_documents WHERE collection_id = %(collection_id)s AND document_id = %(document_id)s",
        {"collection_id": collection_id, "document_id": document_id},
    )


def list_collection_documents(conn: Connection, collection_id: uuid.UUID) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT d.* FROM documents d
        JOIN collection_documents cd ON d.id = cd.document_id
        WHERE cd.collection_id = %(collection_id)s
        ORDER BY d.created_at DESC
        """,
        {"collection_id": collection_id},
    )


# ---- Tags & Document Tags ----


def get_or_create_tag(conn: Connection, name: str, category: str | None = None) -> Row:
    row = fetch_one(
        conn,
        """
        INSERT INTO tags (name, category)
        VALUES (%(name)s, %(category)s)
        ON CONFLICT (name) DO UPDATE
           SET category = COALESCE(EXCLUDED.category, tags.category)
        RETURNING *
        """,
        {"name": name, "category": category},
    )
    if row is None:
        raise RuntimeError(f"Failed to get or create tag {name}")
    return row


def list_tags(conn: Connection) -> list[Row]:
    return fetch_all(conn, "SELECT * FROM tags ORDER BY name ASC")


def tag_document(conn: Connection, document_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    execute(
        conn,
        """
        INSERT INTO document_tags (document_id, tag_id)
        VALUES (%(document_id)s, %(tag_id)s)
        ON CONFLICT DO NOTHING
        """,
        {"document_id": document_id, "tag_id": tag_id},
    )


def untag_document(conn: Connection, document_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    execute(
        conn,
        "DELETE FROM document_tags WHERE document_id = %(document_id)s AND tag_id = %(tag_id)s",
        {"document_id": document_id, "tag_id": tag_id},
    )


def get_document_tags(conn: Connection, document_id: uuid.UUID) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT t.* FROM tags t
        JOIN document_tags dt ON t.id = dt.tag_id
        WHERE dt.document_id = %(document_id)s
        ORDER BY t.name ASC
        """,
        {"document_id": document_id},
    )


# ---- Conversations & Messages ----


def create_conversation(conn: Connection, user_id: uuid.UUID, title: str | None = None) -> Row:
    row = fetch_one(
        conn,
        """
        INSERT INTO conversations (user_id, title)
        VALUES (%(user_id)s, %(title)s)
        RETURNING *
        """,
        {"user_id": user_id, "title": title},
    )
    if row is None:
        raise RuntimeError("Failed to create conversation")
    return row


def ensure_agent_conversation(conn: Connection, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Row | None:
    execute(
        conn,
        """
        INSERT INTO conversations (id, user_id, title)
        VALUES (%(id)s, %(user_id)s, 'New Conversation')
        ON CONFLICT (id) DO NOTHING
        """,
        {"id": conversation_id, "user_id": user_id},
    )
    return get_conversation(conn, conversation_id, user_id)


def get_conversation(conn: Connection, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Row | None:
    return fetch_one(
        conn,
        "SELECT * FROM conversations WHERE id = %(id)s AND user_id = %(user_id)s",
        {"id": conversation_id, "user_id": user_id},
    )


def list_conversations_for_user(
    conn: Connection,
    user_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT * FROM conversations
         WHERE user_id = %(user_id)s
         ORDER BY updated_at DESC
         LIMIT %(limit)s OFFSET %(offset)s
        """,
        {"user_id": user_id, "limit": limit, "offset": offset},
    )


def update_conversation_title(conn: Connection, conversation_id: uuid.UUID, user_id: uuid.UUID, title: str) -> Row:
    row = fetch_one(
        conn,
        """
        UPDATE conversations
           SET title = %(title)s, updated_at = now()
         WHERE id = %(id)s AND user_id = %(user_id)s
        RETURNING *
        """,
        {"id": conversation_id, "user_id": user_id, "title": title},
    )
    if row is None:
        raise LookupError(f"Conversation {conversation_id} not found")
    return row


def delete_conversation(conn: Connection, conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
    execute(
        conn,
        "DELETE FROM conversations WHERE id = %(id)s AND user_id = %(user_id)s",
        {"id": conversation_id, "user_id": user_id},
    )


def add_message(
    conn: Connection,
    *,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    sources_used: list[Any] | None = None,
    tokens_used: int | None = None,
) -> Row:
    row = fetch_one(
        conn,
        """
        INSERT INTO messages (conversation_id, role, content, sources_used, tokens_used)
        VALUES (%(conversation_id)s, %(role)s, %(content)s, %(sources_used)s, %(tokens_used)s)
        RETURNING *
        """,
        {
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "sources_used": psycopg2.extras.Json(sources_used) if sources_used is not None else None,
            "tokens_used": tokens_used,
        },
    )
    if row is None:
        raise RuntimeError("Failed to add message")
    # Touch conversation updated_at
    execute(conn, "UPDATE conversations SET updated_at = now() WHERE id = %(id)s", {"id": conversation_id})
    return row


def list_messages_for_conversation(conn: Connection, conversation_id: uuid.UUID) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT * FROM messages WHERE conversation_id = %(conversation_id)s ORDER BY created_at ASC",
        {"conversation_id": conversation_id},
    )


# ---- Query Traces & Feedback ----


def insert_query_trace(
    conn: Connection,
    *,
    user_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    query_text: str,
    retrieval_mode: str,
    chunks_retrieved: list[Any] | None = None,
    latency_ms: int | None = None,
    llm_model: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    filters_applied: dict[str, Any] | None = None,
) -> Row:
    row = fetch_one(
        conn,
        """
        INSERT INTO query_traces (user_id, conversation_id, query_text, retrieval_mode, chunks_retrieved, latency_ms, llm_model, prompt_tokens, completion_tokens, filters_applied)
        VALUES (%(user_id)s, %(conversation_id)s, %(query_text)s, %(retrieval_mode)s, %(chunks_retrieved)s, %(latency_ms)s, %(llm_model)s, %(prompt_tokens)s, %(completion_tokens)s, %(filters_applied)s)
        RETURNING *
        """,
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "query_text": query_text,
            "retrieval_mode": retrieval_mode,
            "chunks_retrieved": psycopg2.extras.Json(chunks_retrieved) if chunks_retrieved is not None else None,
            "latency_ms": latency_ms,
            "llm_model": llm_model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "filters_applied": psycopg2.extras.Json(filters_applied) if filters_applied is not None else None,
        },
    )
    if row is None:
        raise RuntimeError("Failed to insert query trace")
    return row


def insert_feedback(
    conn: Connection,
    *,
    trace_id: uuid.UUID,
    user_id: uuid.UUID,
    rating: int,
    comment: str | None = None,
) -> Row:
    row = fetch_one(
        conn,
        """
        INSERT INTO feedback (trace_id, user_id, rating, comment)
        VALUES (%(trace_id)s, %(user_id)s, %(rating)s, %(comment)s)
        RETURNING *
        """,
        {"trace_id": trace_id, "user_id": user_id, "rating": rating, "comment": comment},
    )
    if row is None:
        raise RuntimeError("Failed to insert feedback")
    return row


# ---- Settings ----


def get_setting(conn: Connection, key: str) -> Row | None:
    return fetch_one(conn, "SELECT * FROM settings WHERE key = %(key)s", {"key": key})


def set_setting(conn: Connection, key: str, value: Any, updated_by: uuid.UUID | None = None) -> Row:
    row = fetch_one(
        conn,
        """
        INSERT INTO settings (key, value, updated_by, updated_at)
        VALUES (%(key)s, %(value)s::jsonb, %(updated_by)s, now())
        ON CONFLICT (key) DO UPDATE
           SET value = EXCLUDED.value,
               updated_by = EXCLUDED.updated_by,
               updated_at = now()
        RETURNING *
        """,
        {
            "key": key,
            "value": psycopg2.extras.Json(value),
            "updated_by": updated_by,
        },
    )
    if row is None:
        raise RuntimeError(f"Failed to set setting {key}")
    return row


def list_settings(conn: Connection) -> list[Row]:
    return fetch_all(conn, "SELECT * FROM settings ORDER BY key ASC")


# ---- Upload page: owned documents with their tags, collection and sharing ----


def list_accessible_documents(
    conn: Connection, *, user_id: uuid.UUID, user_email: str, user_domain: str | None, limit: int = 200
) -> list[Row]:
    """Documents accessible through current Drive ACLs, with their source owner and collection memberships."""
    return fetch_all(
        conn,
        """
        SELECT d.*,
               (CASE WHEN d.drive_file_id IS NULL THEN d.owner_id = %(user_id)s
                     ELSE lower(COALESCE(d.drive_owner_email, '')) = %(email)s END) AS is_owner,
               (SELECT count(*) FROM chunks ch WHERE ch.document_id = d.id) AS chunk_count,
               CASE WHEN d.drive_file_id IS NULL THEN creator.name ELSE d.drive_owner_name END AS owner_name,
               CASE WHEN d.drive_file_id IS NULL THEN creator.email ELSE d.drive_owner_email END AS owner_email,
               (SELECT u.name FROM users u WHERE u.id = d.imported_by_user_id) AS importer_name,
               (SELECT u.email FROM users u WHERE u.id = d.imported_by_user_id) AS importer_email,
               COALESCE((SELECT array_agg(t.name ORDER BY t.name)
                           FROM document_tags dt JOIN tags t ON t.id = dt.tag_id
                          WHERE dt.document_id = d.id), '{}') AS tags,
               COALESCE((SELECT json_agg(json_build_object('id', c.id, 'name', c.name)
                                         ORDER BY lower(c.name))
                           FROM collection_documents cd
                           JOIN collections c ON c.id = cd.collection_id
                          WHERE cd.document_id = d.id
                            AND (c.owner_id = %(user_id)s OR EXISTS (
                                 SELECT 1 FROM collection_members cm
                                  WHERE cm.collection_id = c.id
                                    AND ((cm.principal_type = 'user' AND cm.principal_value = %(email)s)
                                      OR (cm.principal_type = 'domain' AND %(domain)s <> ''
                                          AND cm.principal_value = %(domain)s))
                            ))), '[]') AS collections,
               COALESCE((SELECT json_agg(json_build_object('type', da.principal_type, 'value', da.principal_value))
                           FROM document_access da WHERE da.document_id = d.id), '[]') AS access
          FROM documents d
          JOIN users creator ON creator.id = d.owner_id
         WHERE EXISTS (
                 SELECT 1 FROM document_access da
                  WHERE da.document_id = d.id
                    AND ((da.principal_type = 'user' AND da.principal_value = %(email)s)
                      OR (da.principal_type = 'domain' AND %(domain)s <> '' AND da.principal_value = %(domain)s))
               )
         ORDER BY d.created_at DESC
         LIMIT %(limit)s
        """,
        {"user_id": user_id, "email": user_email.lower(), "domain": (user_domain or "").lower(), "limit": limit},
    )


def list_collections(conn: Connection, owner_id: uuid.UUID) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT c.id, c.name, c.owner_id, u.name AS owner_name, u.email AS owner_email,
               (c.owner_id = %(id)s) AS is_owner,
               COALESCE(cm_member.drive_role, 'owner') AS role,
               COALESCE((SELECT json_agg(json_build_object(
                   'type', cm.principal_type,
                   'value', cm.principal_value,
                   'role', cm.drive_role
               ) ORDER BY cm.principal_type, cm.principal_value)
                 FROM collection_members cm
                WHERE cm.collection_id = c.id), '[]') AS members
          FROM collections c
          JOIN users u ON u.id = c.owner_id
          LEFT JOIN collection_members cm_member
            ON cm_member.collection_id = c.id
           AND cm_member.principal_type = 'user'
           AND cm_member.principal_value = %(email)s
         WHERE c.owner_id = %(id)s
            OR cm_member.collection_id IS NOT NULL
            OR EXISTS (
                 SELECT 1 FROM collection_members cm_domain
                  WHERE cm_domain.collection_id = c.id
                    AND cm_domain.principal_type = 'domain'
                    AND cm_domain.principal_value = %(domain)s
               )
         ORDER BY lower(c.name)
        """,
        {"id": owner_id, "email": _user_email(conn, owner_id), "domain": _user_domain(conn, owner_id)},
    )


def get_collection(conn: Connection, owner_id: uuid.UUID, collection_id: uuid.UUID) -> Row | None:
    return fetch_one(
        conn,
        "SELECT id, name FROM collections WHERE id = %(id)s AND owner_id = %(o)s",
        {"id": collection_id, "o": owner_id},
    )


def get_collection_by_name(conn: Connection, owner_id: uuid.UUID, name: str) -> Row | None:
    return fetch_one(
        conn,
        "SELECT id, name FROM collections WHERE owner_id = %(o)s AND lower(name) = lower(%(n)s)",
        {"o": owner_id, "n": name},
    )


def create_collection(conn: Connection, owner_id: uuid.UUID, name: str) -> Row:
    row = fetch_one(
        conn,
        "INSERT INTO collections (owner_id, name) VALUES (%(o)s, %(n)s) RETURNING id, name",
        {"o": owner_id, "n": name},
    )
    if row is None:
        raise RuntimeError("Failed to create collection")
    return row


def rename_collection(conn: Connection, collection_id: uuid.UUID, name: str) -> None:
    execute(
        conn,
        "UPDATE collections SET name = %(n)s, updated_at = now() WHERE id = %(id)s",
        {"n": name, "id": collection_id},
    )


def delete_collection(conn: Connection, collection_id: uuid.UUID) -> None:
    """Removes the folder only; its documents stay and become ungrouped."""
    execute(conn, "DELETE FROM collections WHERE id = %(id)s", {"id": collection_id})


def list_collection_document_ids(conn: Connection, owner_id: uuid.UUID, collection_id: uuid.UUID) -> list[uuid.UUID]:
    rows = fetch_all(
        conn,
        """
        SELECT cd.document_id FROM collection_documents cd
         WHERE cd.collection_id = %(c)s
        """,
        {"c": collection_id},
    )
    return [r["document_id"] for r in rows]


def list_tag_names(conn: Connection, owner_id: uuid.UUID) -> list[str]:
    """Tags already used on the user's documents."""
    rows = fetch_all(
        conn,
        """
        SELECT DISTINCT t.name FROM tags t
          JOIN document_tags dt ON dt.tag_id = t.id
          JOIN documents d ON d.id = dt.document_id
         WHERE d.owner_id = %(o)s ORDER BY t.name
        """,
        {"o": owner_id},
    )
    return [r["name"] for r in rows]


def set_document_organization(
    conn: Connection, document_id: uuid.UUID, owner_id: uuid.UUID, *, collection: str | None, tags: list[str]
) -> None:
    """Replaces tags and optionally adds the document to a collection."""
    execute(conn, "DELETE FROM document_tags WHERE document_id = %(d)s", {"d": document_id})
    for name in dict.fromkeys(tags):
        tag = fetch_one(
            conn,
            """
            INSERT INTO tags (name) VALUES (%(name)s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id
            """,
            {"name": name},
        )
        if tag:
            execute(
                conn,
                "INSERT INTO document_tags (document_id, tag_id) VALUES (%(d)s, %(t)s) ON CONFLICT DO NOTHING",
                {"d": document_id, "t": tag["id"]},
            )

    if collection:
        coll = get_collection_by_name(conn, owner_id, collection) or create_collection(conn, owner_id, collection)
        if coll:
            execute(
                conn,
                "INSERT INTO collection_documents (collection_id, document_id) VALUES (%(c)s, %(d)s) ON CONFLICT DO NOTHING",
                {"c": coll["id"], "d": document_id},
            )


def _user_email(conn: Connection, user_id: uuid.UUID) -> str:
    row = fetch_one(conn, "SELECT lower(email) AS email FROM users WHERE id = %(id)s", {"id": user_id})
    return row["email"] if row else ""


def _user_domain(conn: Connection, user_id: uuid.UUID) -> str:
    row = fetch_one(conn, "SELECT lower(COALESCE(domain, '')) AS domain FROM users WHERE id = %(id)s", {"id": user_id})
    return row["domain"] if row else ""


def get_accessible_collection(
    conn: Connection, collection_id: uuid.UUID, *, user_email: str, user_domain: str | None
) -> Row | None:
    return fetch_one(
        conn,
        """
        SELECT c.*, (c.owner_id = u.id) AS is_owner,
               COALESCE(cm.drive_role, 'owner') AS role
          FROM collections c
          JOIN users u ON lower(u.email) = %(email)s
          LEFT JOIN collection_members cm
            ON cm.collection_id = c.id
           AND ((cm.principal_type = 'user' AND cm.principal_value = %(email)s)
             OR (cm.principal_type = 'domain' AND %(domain)s <> '' AND cm.principal_value = %(domain)s))
         WHERE c.id = %(collection_id)s
           AND (c.owner_id = u.id OR cm.collection_id IS NOT NULL)
        """,
        {
            "collection_id": collection_id,
            "email": user_email.lower(),
            "domain": (user_domain or "").lower(),
        },
    )


def list_collection_members(conn: Connection, collection_id: uuid.UUID) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT principal_type, principal_value, drive_role
          FROM collection_members
         WHERE collection_id = %(id)s
         ORDER BY principal_type, principal_value
        """,
        {"id": collection_id},
    )


def replace_collection_members(conn: Connection, collection_id: uuid.UUID, members: list[dict[str, str]]) -> None:
    execute(conn, "DELETE FROM collection_members WHERE collection_id = %(id)s", {"id": collection_id})
    for member in members:
        execute(
            conn,
            """
            INSERT INTO collection_members (collection_id, principal_type, principal_value, drive_role)
            VALUES (%(collection_id)s, %(principal_type)s, %(principal_value)s, %(drive_role)s)
            ON CONFLICT (collection_id, principal_type, principal_value)
            DO UPDATE SET drive_role = EXCLUDED.drive_role
            """,
            {"collection_id": collection_id, **member},
        )


def add_collection_member(conn: Connection, collection_id: uuid.UUID, member: dict[str, str]) -> None:
    execute(
        conn,
        """
        INSERT INTO collection_members (collection_id, principal_type, principal_value, drive_role)
        VALUES (%(collection_id)s, %(principal_type)s, %(principal_value)s, %(drive_role)s)
        ON CONFLICT (collection_id, principal_type, principal_value)
        DO UPDATE SET drive_role = EXCLUDED.drive_role
        """,
        {"collection_id": collection_id, **member},
    )


def remove_collection_member(conn: Connection, collection_id: uuid.UUID, principal_type: str, principal_value: str) -> None:
    execute(
        conn,
        """
        DELETE FROM collection_members
         WHERE collection_id = %(collection_id)s
           AND principal_type = %(principal_type)s
           AND principal_value = %(principal_value)s
        """,
        {
            "collection_id": collection_id,
            "principal_type": principal_type,
            "principal_value": principal_value,
        },
    )


def count_collection_grant_references(
    conn: Connection, document_id: uuid.UUID, principal_type: str, principal_value: str
) -> int:
    row = fetch_one(
        conn,
        """
        SELECT count(*) AS count
          FROM collection_documents cd
          JOIN collection_members cm ON cm.collection_id = cd.collection_id
         WHERE cd.document_id = %(document_id)s
           AND cm.principal_type = %(principal_type)s
           AND cm.principal_value = %(principal_value)s
        """,
        {
            "document_id": document_id,
            "principal_type": principal_type,
            "principal_value": principal_value,
        },
    )
    return int(row["count"]) if row else 0


def get_collection_drive_grant(
    conn: Connection, document_id: uuid.UUID, principal_type: str, principal_value: str
) -> Row | None:
    return fetch_one(
        conn,
        """
        SELECT permission_id FROM collection_drive_grants
         WHERE document_id = %(document_id)s
           AND principal_type = %(principal_type)s
           AND principal_value = %(principal_value)s
        """,
        {"document_id": document_id, "principal_type": principal_type, "principal_value": principal_value},
    )


def save_collection_drive_grant(
    conn: Connection, document_id: uuid.UUID, principal_type: str, principal_value: str, permission_id: str
) -> None:
    execute(
        conn,
        """
        INSERT INTO collection_drive_grants (document_id, principal_type, principal_value, permission_id)
        VALUES (%(document_id)s, %(principal_type)s, %(principal_value)s, %(permission_id)s)
        ON CONFLICT (document_id, principal_type, principal_value)
        DO UPDATE SET permission_id = EXCLUDED.permission_id
        """,
        {
            "document_id": document_id,
            "principal_type": principal_type,
            "principal_value": principal_value,
            "permission_id": permission_id,
        },
    )


def delete_collection_drive_grant(
    conn: Connection, document_id: uuid.UUID, principal_type: str, principal_value: str
) -> None:
    execute(
        conn,
        """
        DELETE FROM collection_drive_grants
         WHERE document_id = %(document_id)s
           AND principal_type = %(principal_type)s
           AND principal_value = %(principal_value)s
        """,
        {"document_id": document_id, "principal_type": principal_type, "principal_value": principal_value},
    )


def add_document_to_collection(conn: Connection, collection_id: uuid.UUID, document_id: uuid.UUID) -> None:
    execute(
        conn,
        """
        INSERT INTO collection_documents (collection_id, document_id)
        VALUES (%(collection_id)s, %(document_id)s)
        ON CONFLICT DO NOTHING
        """,
        {"collection_id": collection_id, "document_id": document_id},
    )


def remove_document_from_collection(conn: Connection, collection_id: uuid.UUID, document_id: uuid.UUID) -> None:
    execute(
        conn,
        "DELETE FROM collection_documents WHERE collection_id = %(collection_id)s AND document_id = %(document_id)s",
        {"collection_id": collection_id, "document_id": document_id},
    )


def remove_document_user_access(conn: Connection, document_id: uuid.UUID, user_email: str) -> None:
    execute(
    conn,
    """
    DELETE FROM document_access
     WHERE document_id = %(document_id)s
       AND principal_type = 'user'
       AND principal_value = %(email)s
    """,
    {"document_id": document_id, "email": user_email.lower()},
    )


def set_document_sharing_option(conn: Connection, document_id: uuid.UUID, sharing_option: str) -> None:
    execute(
        conn,
        "UPDATE documents SET sharing_option = %(s)s, updated_at = now() WHERE id = %(id)s",
        {"s": sharing_option, "id": document_id},
    )


# ---- Admin: users and every document's access ----

PENDING_PREFIX = "pending:"


def list_users_with_counts(conn: Connection) -> list[Row]:
    """All users, newest first, with how many documents each owns. `pending` is true for accounts an
    admin added that haven't signed in yet."""
    return fetch_all(
        conn,
        """
        SELECT u.id, u.email, u.name, u.role, u.status, u.created_at, u.last_login_at,
               (u.google_sub LIKE %(prefix)s) AS pending,
               (SELECT count(*) FROM documents d WHERE d.owner_id = u.id) AS document_count
          FROM users u
         ORDER BY u.created_at DESC
        """,
        {"prefix": PENDING_PREFIX + "%"},
    )


def get_user_by_email(conn: Connection, email: str) -> Row | None:
    return fetch_one(conn, "SELECT * FROM users WHERE lower(email) = lower(%(e)s) LIMIT 1", {"e": email})


def insert_pending_user(conn: Connection, *, email: str, name: str, domain: str | None, role: str) -> Row:
    """Creates an account for someone who hasn't signed in. Their first Google sign-in claims it."""
    token = uuid.uuid4().hex
    row = fetch_one(
        conn,
        """
        INSERT INTO users (firebase_uid, google_sub, email, domain, name, role)
        VALUES (%(uid)s, %(sub)s, %(email)s, %(domain)s, %(name)s, %(role)s)
        RETURNING *
        """,
        {"uid": PENDING_PREFIX + token, "sub": PENDING_PREFIX + token, "email": email, "domain": domain, "name": name, "role": role},
    )
    if row is None:
        raise RuntimeError("Failed to add user")
    return row


def lock_pending_user_by_email(conn: Connection, email: str) -> Row | None:
    """A user an admin added in advance, matched by email at their first sign-in."""
    return fetch_one(
        conn,
        "SELECT * FROM users WHERE lower(email) = lower(%(e)s) AND google_sub LIKE %(prefix)s FOR UPDATE",
        {"e": email, "prefix": PENDING_PREFIX + "%"},
    )


def claim_pending_user(conn: Connection, user_id: uuid.UUID, *, google_sub: str) -> None:
    execute(conn, "UPDATE users SET google_sub = %(sub)s WHERE id = %(id)s", {"id": user_id, "sub": google_sub})


def set_user_role_status(conn: Connection, user_id: uuid.UUID, *, role: str, status: str) -> Row | None:
    return fetch_one(
        conn,
        "UPDATE users SET role = %(role)s, status = %(status)s, updated_at = now() WHERE id = %(id)s RETURNING *",
        {"id": user_id, "role": role, "status": status},
    )


def count_active_admins(conn: Connection) -> int:
    row = fetch_one(conn, "SELECT count(*) AS n FROM users WHERE role = 'admin' AND status = 'active'")
    return int(row["n"]) if row else 0


def delete_user(conn: Connection, user_id: uuid.UUID) -> None:
    """Removes the account and, through foreign keys, their documents, chunks, collections and tokens."""
    execute(conn, "DELETE FROM users WHERE id = %(id)s", {"id": user_id})


def list_all_documents(conn: Connection, limit: int = 500) -> list[Row]:
    """Every document with its owner, tags and full access list. Metadata only, never the text."""
    return fetch_all(
        conn,
        """
        SELECT d.id, d.title, d.file_type, d.origin, d.status, d.status_message, d.sharing_option,
               d.drive_file_id, d.file_size_bytes, d.created_at, d.updated_at,
               CASE WHEN d.drive_file_id IS NULL THEN u.name ELSE d.drive_owner_name END AS owner_name,
               CASE WHEN d.drive_file_id IS NULL THEN u.email ELSE d.drive_owner_email END AS owner_email,
               importer.name AS importer_name, importer.email AS importer_email,
               (SELECT count(*) FROM chunks ch WHERE ch.document_id = d.id) AS chunk_count,
               COALESCE((SELECT array_agg(t.name ORDER BY t.name)
                           FROM document_tags dt JOIN tags t ON t.id = dt.tag_id
                          WHERE dt.document_id = d.id), '{}') AS tags,
               COALESCE((SELECT json_agg(json_build_object('type', da.principal_type, 'value', da.principal_value,
                                                           'origin', da.origin) ORDER BY da.principal_type, da.principal_value)
                           FROM document_access da WHERE da.document_id = d.id), '[]') AS access
          FROM documents d
          JOIN users u ON u.id = d.owner_id
          LEFT JOIN users importer ON importer.id = COALESCE(d.imported_by_user_id, d.owner_id)
         ORDER BY d.created_at DESC
         LIMIT %(limit)s
        """,
        {"limit": limit},
    )
