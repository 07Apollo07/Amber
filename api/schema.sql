-- Amber schema (Phase 2: authentication tables).
--
-- Apply as the schema owner (amber_migrator), never as the app role:
--   psql "$AMBER_MIGRATOR_DSN" -v ON_ERROR_STOP=1 -f schema.sql
--
-- Idempotent: safe to re-run. New tables are appended in later phases; changes to existing
-- tables go in as explicit, reviewed ALTER statements at the end of this file.

BEGIN;

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

-- Least privilege for the API role, once the infra setup has created it.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'amber_app') THEN
    GRANT SELECT, INSERT, UPDATE ON users TO amber_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON oauth_tokens TO amber_app;
    GRANT INSERT ON audit_log TO amber_app;  -- append-only: no SELECT, UPDATE or DELETE
    GRANT SELECT, INSERT, DELETE ON revoked_sessions TO amber_app;
  END IF;
END $$;

COMMIT;
