-- Amber schema (Phase 2: authentication tables).
--
-- Apply as the schema owner (amber_migrator), never as the app role:
--   psql "$AMBER_MIGRATOR_DSN" -v ON_ERROR_STOP=1 -f schema.sql
--
-- Idempotent: safe to re-run. New tables are appended in later phases; changes to existing
-- tables go in as explicit, reviewed ALTER statements at the end of this file.

BEGIN;

-- The tables below use FORCE ROW LEVEL SECURITY, which applies the policies to their owner too.
-- This script runs as the owner and rewrites existing rows (the duplicate-document cleanup), so it
-- enables the trusted-sync flag for this transaction only.
SELECT set_config('app.drive_sync', 'true', true);

CREATE TABLE IF NOT EXISTS users (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firebase_uid   varchar(128) NOT NULL UNIQUE,
    google_sub     varchar(255) NOT NULL UNIQUE,
    email          varchar(320) NOT NULL,
    domain         varchar(255),                       -- Google Workspace `hd` claim
    name           varchar(255) NOT NULL,
    picture_url    varchar(2048),
    role           varchar(16)  NOT NULL DEFAULT 'member',
    status         varchar(16)  NOT NULL DEFAULT 'active',
    created_at     timestamptz  NOT NULL DEFAULT now(),
    updated_at     timestamptz  NOT NULL DEFAULT now(),
    last_login_at  timestamptz,
    CONSTRAINT ck_users_role   CHECK (role IN ('admin', 'member')),
    CONSTRAINT ck_users_status CHECK (status IN ('active', 'deactivated'))
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);

-- A user's Google refresh token, envelope-encrypted (see amber/util/crypto.py).
CREATE TABLE IF NOT EXISTS oauth_tokens (
    user_id                  uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    encrypted_refresh_token  bytea         NOT NULL,
    kms_key_version          varchar(512)  NOT NULL,
    scopes                   varchar(2048) NOT NULL,  -- space-separated, as granted by Google
    created_at               timestamptz   NOT NULL DEFAULT now(),
    updated_at               timestamptz   NOT NULL DEFAULT now()
);

-- Append-only audit trail.
CREATE TABLE IF NOT EXISTS audit_log (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at             timestamptz  NOT NULL DEFAULT now(),
    actor_user_id  uuid,
    actor_email    varchar(320),
    action         varchar(64)  NOT NULL,
    target         varchar(512),
    detail         jsonb,
    ip             varchar(64)
);
CREATE INDEX IF NOT EXISTS ix_audit_log_at            ON audit_log (at);
CREATE INDEX IF NOT EXISTS ix_audit_log_actor_user_id ON audit_log (actor_user_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_action        ON audit_log (action);

-- Session cookies signed out on one device, kept until they'd have expired anyway.
-- Firebase can only revoke all of a user's sessions, so per-device sign-out needs this list.
CREATE TABLE IF NOT EXISTS revoked_sessions (
    token_hash  bytea PRIMARY KEY,           -- SHA-256 of the session cookie, never the cookie itself
    expires_at  timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_revoked_sessions_expires_at ON revoked_sessions (expires_at);

-- Phase 3: Documents, Access Control, Chunks, Search, Conversations, Traces & Settings.

CREATE TABLE IF NOT EXISTS documents (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- owner_id is retained as the Amber record creator for compatibility. Drive ownership is stored separately.
    owner_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    imported_by_user_id uuid REFERENCES users (id) ON DELETE SET NULL,
    drive_owner_email varchar(320),
    drive_owner_name  varchar(255),
    origin           varchar(32) NOT NULL,
    drive_file_id    varchar(255),
    title            varchar(512) NOT NULL,
    file_type        varchar(64) NOT NULL,
    file_size_bytes  bigint,
    mime_type        varchar(255),
    sha256           varchar(64),
    status           varchar(32) NOT NULL DEFAULT 'queued',
    status_message   text,
    sharing_option   varchar(32) NOT NULL DEFAULT 'private',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    last_synced_at   timestamptz,
    CONSTRAINT ck_documents_origin CHECK (origin IN ('desktop_upload', 'drive_sync')),
    CONSTRAINT ck_documents_status CHECK (status IN ('queued', 'saving_to_drive', 'parsing', 'indexing', 'indexed', 'failed')),
    CONSTRAINT ck_documents_sharing CHECK (sharing_option IN ('private', 'specific_people', 'domain'))
);
CREATE INDEX IF NOT EXISTS ix_documents_owner_id ON documents (owner_id);
CREATE INDEX IF NOT EXISTS ix_documents_drive_file_id ON documents (drive_file_id);
CREATE INDEX IF NOT EXISTS ix_documents_status ON documents (status);
CREATE INDEX IF NOT EXISTS ix_documents_sha256 ON documents (sha256);

CREATE TABLE IF NOT EXISTS document_access (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id      uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    principal_type   varchar(16) NOT NULL,
    principal_value  varchar(320) NOT NULL,
    origin           varchar(16) NOT NULL DEFAULT 'manual',
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_document_access_principal UNIQUE (document_id, principal_type, principal_value),
    CONSTRAINT ck_document_access_principal_type CHECK (principal_type IN ('user', 'domain')),
    CONSTRAINT ck_document_access_origin CHECK (origin IN ('manual', 'drive_sync'))
);
CREATE INDEX IF NOT EXISTS ix_document_access_lookup ON document_access (principal_type, principal_value);
CREATE INDEX IF NOT EXISTS ix_document_access_document_id ON document_access (document_id);

CREATE TABLE IF NOT EXISTS drive_sync_state (
    user_id          uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    page_token       text NOT NULL,
    channel_id       varchar(255) NOT NULL UNIQUE,
    resource_id      varchar(255) NOT NULL,
    token_hash       varchar(64) NOT NULL,
    channel_expires  timestamptz NOT NULL,
    last_synced_at   timestamptz,
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_drive_sync_state_expiration ON drive_sync_state (channel_expires);

-- Debounce queue: a webhook upserts a row and moves last_change_at to now(); the file is re-indexed once
-- last_change_at is older than the quiet period (or first_change_at older than the max wait).
CREATE TABLE IF NOT EXISTS drive_pending_reindex (
    document_id      uuid PRIMARY KEY REFERENCES documents (id) ON DELETE CASCADE,
    user_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    drive_file_id    varchar(255) NOT NULL,
    first_change_at  timestamptz NOT NULL DEFAULT now(),
    last_change_at   timestamptz NOT NULL DEFAULT now(),
    claimed_at       timestamptz,
    attempts         integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_drive_pending_reindex_last_change ON drive_pending_reindex (last_change_at);

CREATE TABLE IF NOT EXISTS chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    ord          integer NOT NULL,
    text         text NOT NULL,
    page         integer,
    embedding    vector(1536),
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_chunks_document_id ON chunks (document_id);
CREATE INDEX IF NOT EXISTS ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS collections (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name         varchar(255) NOT NULL,
    description  text,
    color        varchar(32),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_collections_owner_id ON collections (owner_id);

CREATE TABLE IF NOT EXISTS collection_documents (
    collection_id  uuid NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    document_id    uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (collection_id, document_id)
);
CREATE INDEX IF NOT EXISTS ix_collection_documents_doc ON collection_documents (document_id);

CREATE TABLE IF NOT EXISTS collection_members (
    collection_id  uuid NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    principal_type varchar(16) NOT NULL,
    principal_value varchar(320) NOT NULL,
    drive_role     varchar(16) NOT NULL DEFAULT 'reader',
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (collection_id, principal_type, principal_value),
    CONSTRAINT ck_collection_members_principal_type CHECK (principal_type IN ('user', 'domain')),
    CONSTRAINT ck_collection_members_drive_role CHECK (drive_role IN ('reader', 'writer'))
);
CREATE INDEX IF NOT EXISTS ix_collection_members_principal
    ON collection_members (principal_type, principal_value);

-- Only permissions created by Amber for collection membership are recorded here.
-- Direct Drive grants and grants managed outside Amber are never removed by collection changes.
CREATE TABLE IF NOT EXISTS collection_drive_grants (
    document_id    uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    principal_type varchar(16) NOT NULL,
    principal_value varchar(320) NOT NULL,
    permission_id  varchar(255) NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, principal_type, principal_value),
    CONSTRAINT ck_collection_drive_grants_principal_type CHECK (principal_type IN ('user', 'domain'))
);

CREATE TABLE IF NOT EXISTS tags (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        varchar(64) NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_tags (
    document_id  uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    tag_id       uuid NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, tag_id)
);

-- A Drive file is one indexed source, even if multiple Amber users previously imported it.
DO $$
DECLARE
    duplicate_group record;
    keeper_id uuid;
BEGIN
    FOR duplicate_group IN
        SELECT drive_file_id,
               (array_agg(id ORDER BY (status = 'indexed') DESC, updated_at DESC, id))[1] AS keeper_id
          FROM documents
         WHERE drive_file_id IS NOT NULL
         GROUP BY drive_file_id
        HAVING count(*) > 1
    LOOP
        keeper_id := duplicate_group.keeper_id;

        INSERT INTO collection_documents (collection_id, document_id)
        SELECT collection_id, keeper_id
          FROM collection_documents
         WHERE document_id IN (SELECT id FROM documents WHERE drive_file_id = duplicate_group.drive_file_id)
        ON CONFLICT DO NOTHING;
        INSERT INTO document_tags (document_id, tag_id)
        SELECT keeper_id, tag_id
          FROM document_tags
         WHERE document_id IN (SELECT id FROM documents WHERE drive_file_id = duplicate_group.drive_file_id)
        ON CONFLICT DO NOTHING;
        INSERT INTO document_access (document_id, principal_type, principal_value, origin)
        SELECT keeper_id, principal_type, principal_value, origin
          FROM document_access
         WHERE document_id IN (SELECT id FROM documents WHERE drive_file_id = duplicate_group.drive_file_id)
        ON CONFLICT (document_id, principal_type, principal_value) DO NOTHING;

        DELETE FROM chunks
         WHERE document_id IN (
             SELECT id FROM documents
              WHERE drive_file_id = duplicate_group.drive_file_id AND id <> keeper_id
         );
        DELETE FROM collection_documents
         WHERE document_id IN (
             SELECT id FROM documents
              WHERE drive_file_id = duplicate_group.drive_file_id AND id <> keeper_id
         );
        DELETE FROM document_tags
         WHERE document_id IN (
             SELECT id FROM documents
              WHERE drive_file_id = duplicate_group.drive_file_id AND id <> keeper_id
         );
        DELETE FROM documents
         WHERE drive_file_id = duplicate_group.drive_file_id AND id <> keeper_id;
    END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_drive_file_id
    ON documents (drive_file_id) WHERE drive_file_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS query_traces (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    query                text NOT NULL,
    rewritten_query      text,
    filters              jsonb,
    retrieved_chunk_ids  jsonb,
    cited_chunk_ids      jsonb,
    hidden_count         integer NOT NULL DEFAULT 0,
    model                varchar(128),
    tokens               integer,
    latency_ms           integer,
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_query_traces_user_id ON query_traces (user_id);
CREATE INDEX IF NOT EXISTS ix_query_traces_created_at ON query_traces (created_at);

CREATE TABLE IF NOT EXISTS conversations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title       varchar(255) NOT NULL DEFAULT 'New Conversation',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id);

CREATE TABLE IF NOT EXISTS messages (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role             varchar(16) NOT NULL,
    content          text NOT NULL,
    trace_id         uuid REFERENCES query_traces (id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_messages_role CHECK (role IN ('user', 'assistant', 'system'))
);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages (conversation_id);

CREATE TABLE IF NOT EXISTS feedback (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    message_id  uuid REFERENCES messages (id) ON DELETE CASCADE,
    trace_id    uuid REFERENCES query_traces (id) ON DELETE CASCADE,
    rating      varchar(16) NOT NULL,
    comment     text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_feedback_rating CHECK (rating IN ('thumbs_up', 'thumbs_down'))
);

CREATE TABLE IF NOT EXISTS settings (
    key         varchar(128) PRIMARY KEY,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Row-Level Security
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_access ENABLE ROW LEVEL SECURITY;
-- FORCE: the policies also bind the table owner, so connecting the app as the owner (easy to do in
-- local dev) fails closed and can't silently skip access filtering. Superusers and BYPASSRLS roles
-- still bypass RLS, so the app must never use one.
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE document_access FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_access_internal_policy ON document_access;
CREATE POLICY document_access_internal_policy ON document_access
  FOR ALL
  USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS documents_access_policy ON documents;
CREATE POLICY documents_access_policy ON documents
  FOR ALL
  USING (
    current_setting('app.drive_sync', true) = 'true'
    OR EXISTS (
      SELECT 1 FROM document_access da
      WHERE da.document_id = documents.id
        AND (
          (da.principal_type = 'user' AND da.principal_value = NULLIF(current_setting('app.user_email', true), ''))
          OR (da.principal_type = 'domain' AND da.principal_value = NULLIF(current_setting('app.user_domain', true), ''))
        )
    )
  )
  WITH CHECK (true);

DROP POLICY IF EXISTS chunks_access_policy ON chunks;
CREATE POLICY chunks_access_policy ON chunks
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM documents d
      WHERE d.id = chunks.document_id
    )
  );

-- Least privilege for the API role, once the infra setup has created it.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'amber_app') THEN
    GRANT SELECT, INSERT, UPDATE ON users TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON oauth_tokens TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON drive_sync_state TO amber_app;
    GRANT INSERT ON audit_log TO amber_app;  -- append-only: no SELECT, UPDATE or DELETE
    GRANT SELECT, INSERT, DELETE ON revoked_sessions TO amber_app;

    GRANT SELECT, INSERT, UPDATE, DELETE ON documents TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON document_access TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON drive_sync_state TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON drive_pending_reindex TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON chunks TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON collections TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON collection_documents TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON collection_members TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON collection_drive_grants TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON tags TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON document_tags TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON conversations TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON messages TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON query_traces TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON feedback TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON settings TO amber_app;
  END IF;
END $$;

-- Admin page: settings record who changed them, and admins can delete users.
ALTER TABLE settings ADD COLUMN IF NOT EXISTS updated_by uuid REFERENCES users (id) ON DELETE SET NULL;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'amber_app') THEN
    GRANT DELETE ON users TO amber_app;
  END IF;
END $$;

-- Drive source ownership is distinct from the Amber user who first indexed the file.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS imported_by_user_id uuid REFERENCES users (id) ON DELETE SET NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS drive_owner_email varchar(320);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS drive_owner_name varchar(255);
UPDATE documents SET imported_by_user_id = owner_id WHERE imported_by_user_id IS NULL;

COMMIT;
