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


# ---- Documents ----


def upsert_document(
    conn: Connection,
    *,
    owner_id: uuid.UUID,
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
            "SELECT id FROM documents WHERE owner_id = %(owner_id)s AND drive_file_id = %(drive_file_id)s",
            {"owner_id": owner_id, "drive_file_id": drive_file_id},
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
            INSERT INTO documents (owner_id, origin, drive_file_id, title, file_type, file_size_bytes, mime_type, sha256, status, status_message, sharing_option, updated_at)
            VALUES (%(owner_id)s, %(origin)s, %(drive_file_id)s, %(title)s, %(file_type)s, %(file_size_bytes)s, %(mime_type)s, %(sha256)s, %(status)s, %(status_message)s, %(sharing_option)s, now())
            RETURNING *
            """,
            {
                "owner_id": owner_id,
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
        "SELECT * FROM documents WHERE owner_id = %(owner_id)s AND drive_file_id = %(drive_file_id)s",
        {"owner_id": owner_id, "drive_file_id": drive_file_id},
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
         WHERE d.owner_id = %(user_id)s
            OR EXISTS (
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
        try:
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
        except Exception:
            pass


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

    filters = []
    if collection_ids:
        filters.append(
            "d.id IN (SELECT document_id FROM collection_documents WHERE collection_id = ANY(%(collection_ids)s))"
        )
        params["collection_ids"] = collection_ids
    if file_types:
        filters.append("d.file_type = ANY(%(file_types)s)")
        params["file_types"] = file_types

    where_clause = "WHERE " + " AND ".join(filters) if filters else ""

    if query_embedding and query_text:
        sql = f"""
        SELECT c.id, c.document_id, c.ord, c.text AS content, c.page,
               d.title AS document_title, d.source AS document_source, d.source_url, d.file_type,
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
               d.title AS document_title, d.source AS document_source, d.source_url, d.file_type,
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
               d.title AS document_title, d.source AS document_source, d.source_url, d.file_type,
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
               d.title AS document_title, d.source AS document_source, d.source_url, d.file_type
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


def get_conversation(conn: Connection, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Row | None:
    return fetch_one(
        conn,
        "SELECT * FROM conversations WHERE id = %(id)s AND user_id = %(user_id)s",
        {"id": conversation_id, "user_id": user_id},
    )


def list_conversations_for_user(conn: Connection, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT * FROM conversations WHERE user_id = %(user_id)s ORDER BY updated_at DESC LIMIT %(limit)s OFFSET %(offset)s",
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


def list_owned_documents(conn: Connection, owner_id: uuid.UUID, limit: int = 200) -> list[Row]:
    """The user's own documents, newest first, each with `tags` (names), `collection` (name or None)
    and `access` (the user/domain grants that are not the owner's own email)."""
    return fetch_all(
        conn,
        """
        SELECT d.*,
               COALESCE((SELECT array_agg(t.name ORDER BY t.name)
                           FROM document_tags dt JOIN tags t ON t.id = dt.tag_id
                          WHERE dt.document_id = d.id), '{}') AS tags,
               (SELECT c.id FROM collection_documents cd JOIN collections c ON c.id = cd.collection_id
                 WHERE cd.document_id = d.id AND c.owner_id = d.owner_id LIMIT 1) AS collection_id,
               (SELECT c.name FROM collection_documents cd JOIN collections c ON c.id = cd.collection_id
                 WHERE cd.document_id = d.id AND c.owner_id = d.owner_id LIMIT 1) AS collection,
               COALESCE((SELECT json_agg(json_build_object('type', da.principal_type, 'value', da.principal_value))
                           FROM document_access da WHERE da.document_id = d.id), '[]') AS access
          FROM documents d
         WHERE d.owner_id = %(owner_id)s
         ORDER BY d.created_at DESC
         LIMIT %(limit)s
        """,
        {"owner_id": owner_id, "limit": limit},
    )


def list_collections(conn: Connection, owner_id: uuid.UUID) -> list[Row]:
    return fetch_all(
        conn, "SELECT id, name FROM collections WHERE owner_id = %(o)s ORDER BY lower(name)", {"o": owner_id}
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
          JOIN documents d ON d.id = cd.document_id
         WHERE cd.collection_id = %(c)s AND d.owner_id = %(o)s
        """,
        {"c": collection_id, "o": owner_id},
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
    """Replaces the document's tags and collection. Collections are created by name on first use."""
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

    execute(
        conn,
        """
        DELETE FROM collection_documents cd USING collections c
         WHERE cd.collection_id = c.id AND cd.document_id = %(d)s AND c.owner_id = %(o)s
        """,
        {"d": document_id, "o": owner_id},
    )
    if collection:
        coll = get_collection_by_name(conn, owner_id, collection) or create_collection(conn, owner_id, collection)
        if coll:
            execute(
                conn,
                "INSERT INTO collection_documents (collection_id, document_id) VALUES (%(c)s, %(d)s) ON CONFLICT DO NOTHING",
                {"c": coll["id"], "d": document_id},
            )


def set_document_sharing_option(conn: Connection, document_id: uuid.UUID, sharing_option: str) -> None:
    execute(
        conn,
        "UPDATE documents SET sharing_option = %(s)s, updated_at = now() WHERE id = %(id)s",
        {"s": sharing_option, "id": document_id},
    )
