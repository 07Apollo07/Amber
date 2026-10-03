# Amber: Code Audit Report

**Date:** 2026-10-03
**Scope:** `api` (FastAPI) and `ui` (Next.js), as of Phase 2 (Google sign-in with Drive permission)
**Status:** all security issues and all but one logic bug are fixed. The duplicated and unused code is listed but not changed yet.

## 1. Action required

1. **Create the `revoked_sessions` table.** Single-device sign-out needs it. The definition and grants are in `api/schema.sql`:

   ```sql
   CREATE TABLE IF NOT EXISTS revoked_sessions (
       token_hash  bytea PRIMARY KEY,   -- SHA-256 of the session cookie, never the cookie itself
       expires_at  timestamptz NOT NULL
   );
   CREATE INDEX IF NOT EXISTS ix_revoked_sessions_expires_at ON revoked_sessions (expires_at);
   GRANT SELECT, INSERT, DELETE ON revoked_sessions TO amber_app;
   ```

2. **Set `AMBER_TRUSTED_PROXIES`.** Use `127.0.0.1/32` for local dev, where the Next.js dev server proxies `/api`. In GCP, use the load balancer's IP ranges.

3. **Check the API's settings.** The API now refuses to start, outside tests, if any of these is missing or invalid:
   - `AMBER_GOOGLE_OAUTH_CLIENT_ID` and `AMBER_GOOGLE_OAUTH_CLIENT_SECRET`
   - `AMBER_FIREBASE_PROJECT_ID` and `AMBER_FIREBASE_WEB_API_KEY`
   - `AMBER_STATE_COOKIE_KEY`, which must be a valid Fernet key
   - `AMBER_DATABASE_DSN`
   - `AMBER_TOKEN_KMS_KEY`, or outside prod `AMBER_LOCAL_TOKEN_KEY`

## 2. Security issues

| # | Severity | Issue | Status | What changed |
|---|---|---|---|---|
| S1 | High | Tests emptied `users`, `oauth_tokens` and `audit_log` in whatever database `AMBER_TEST_DATABASE_DSN` pointed to. A wrong value would wipe real data. | ✅ Fixed | All database-backed tests removed (see §5). No test connects to a database any more. |
| S2 | Medium | Sign-out only cleared browser cookies. The Firebase session cookie stayed valid server-side for up to 5 days, so a stolen copy kept working. | ✅ Fixed | Sign-out records the cookie's SHA-256 hash in `revoked_sessions` until it expires. Every request checks it. A copied cookie dies immediately, and other devices stay signed in. |
| S3 | Medium | Drive disconnect never checked Google's response. Users were told "disconnected" even when Google still held the grant. | ✅ Fixed | `revoke()` now checks the status; Google's "already revoked" answer counts as success. If Google can't confirm, the token is kept and the user sees "try again" (HTTP 502). If the stored token is unreadable, Amber deletes its copy and tells the user to also remove access in their Google account. |
| S4 | Medium | The audit log recorded the proxy's IP, not the user's. Naively trusting `X-Forwarded-For` would make it spoofable. | ✅ Fixed | New `amber/util/net.py`. `X-Forwarded-For` is only used when the direct peer is in `AMBER_TRUSTED_PROXIES`. It's read right-to-left, so client-supplied entries are ignored. |
| S5 | Medium | Every request called Firebase over the network to check revocation, and the sign-in endpoints had no rate limits. That meant added latency, quota burn and an easy DoS lever. | ✅ Fixed | **Session checks:** the signature and expiry are still verified locally on every request; only Firebase's "revoked before" timestamp is cached, for 60 s. **Limits:** sign-in is limited to 20 requests a minute per IP, and sign-out and disconnect to 10. A rate-limited sign-in lands on `/login` with a clear message. **Trade-off:** "sign out of all devices" can take up to 60 s to reach other API instances, while single-device sign-out and deactivation stay instant. |
| S6 | Low/Med | Missing secrets passed startup and only failed at the first sign-in (500). | ✅ Fixed | Required settings are validated at startup in dev and prod (see §1.3). |
| S7 | Low | `.env` was read in every environment. A stray `.env` in a prod image would override settings. | ✅ Fixed | `get_settings()` never reads `.env` when `AMBER_ENV=prod`. |
| S8 | Low | A bootstrap admin was matched by email on every sign-in. A reassigned Workspace mailbox would make the new owner admin. | ✅ Fixed | A bootstrap email only grants admin when the account is first created. Existing accounts are never promoted afterwards. |
| S9 | Low | A deactivated user's profile was updated, and could even be promoted, before the sign-in was refused. | ✅ Fixed | Deactivated users are refused before any write; their row is left untouched. |
| S10 | Low | HSTS had `preload` from day one, which is effectively permanent once submitted. | ✅ Fixed | `preload` removed. Add it back only once every subdomain is confirmed HTTPS-only. |
| S11 | Info | The CSP allows `style-src 'unsafe-inline'`, which Radix needs for popover positioning. | Accepted | Documented trade-off. The rest of the CSP is strict (nonce scripts, `frame-ancestors 'none'`, `object-src 'none'`). |

## 3. Logic bugs

| # | Issue | Status | What changed |
|---|---|---|---|
| L1 | A returning user without a stored refresh token had their account row saved before the second consent screen. Cancelling there left an account with no session. | ✅ Fixed | That path now rolls back; nothing is saved until consent completes. |
| L2 | Dropped files appeared as "Queued" rows that never progressed, which looked like real pending uploads. | ✅ Fixed | No fake rows. Dropping files now says uploading isn't available yet. |
| L3 | Quick answer and Chat contain answer-rendering code that no current state reaches. | Kept on purpose | It's the hook where Phase 5's real answers plug in. It doesn't affect current behaviour. |
| L4 | The login audit row computed "Drive connected" differently from `/api/me`, so the two could disagree. | ✅ Fixed | One shared rule, `models.drive_connected(has_refresh_token, scopes)`, used by both. |
| L5 | The cookie-name comment in `ui/lib/auth-paths.ts` was out of date. | ✅ Fixed | Comment corrected. |
| L6 | `PLAN.md` Phase 1 described MSW, `middleware.ts`, an OpenAPI contract and a light/dark theme. None of these exist. | ✅ Fixed | `PLAN.md` now matches the code. Phase 2 also records the new sign-out, rate-limit and audit-IP behaviour. |

## 4. Duplicated and unused code (not changed yet)

**Duplicated**
1. The return-to safety regex is copied in `amber/api/auth.py` (`_SAFE_PATH`) and `ui/lib/auth-paths.ts` (`safeReturnTo`).
2. Cookie names are defined in `security.cookie_names()` and again in `lib/auth-paths.ts`.
3. The API address default (`http://127.0.0.1:8000`) is in both `next.config.ts` and `lib/session.ts`.
4. Cookie attributes (`path`, `secure`, `samesite`) are repeated across `security.py` and `auth.py`.
5. The Drive "Connected" / "Not connected" pills in `profile-page.tsx` re-implement the `StatusBadge` styling.
6. `User` and `SessionUser` in `lib/types.ts` overlap heavily.

**Unused or placeholder**
1. Screens for data that doesn't exist yet:
   - answer, sources, trace and feedback components;
   - admin table rows and the analytics chart;
   - the document edit and delete dialogs.

   All are fed by empty lists. Keep them for Phases 4–6 on purpose, or delete until then.
2. The "demo only" buttons, and Admin › Settings, which has hard-coded values and nothing behind it.
3. `psycopg2-binary` is used where psycopg2's maintainers recommend building `psycopg2` from source for production.

Already removed: five unused shadcn components (alert, scroll-area, separator, skeleton, switch), the `next-themes` package, an unused error class, an unused query helper, the unused Google access token and an unused audit parameter.

## 5. Tests removed

Tests that could cause harm or fail depending on when they run were removed:

| Removed | Why |
|---|---|
| All 48 database-backed tests: `test_session.py`, `test_db.py` and the sign-in callback tests in `test_auth_flow.py` | Each one emptied `users`, `oauth_tokens`, `audit_log` and `revoked_sessions` in the configured database. Run against the wrong database at the wrong time, they would wipe real data. |
| Among those, the two rate-limit tests | They also counted requests within a fixed one-minute window. A run crossing a minute boundary could fail at random. |

**Remaining: 42 tests.** These are the 25 tests that never needed a database, plus 17 new ones that check the same rules without one. They never connect to a database or call Google or Firebase, and they don't depend on timing. They cover:
- refresh-token encryption: round trip, binding to the owning user, tamper detection;
- config validation: prod safety checks, required settings, `.env` ignored in prod;
- client-IP resolution, including spoofing attempts;
- the sign-in redirect: PKCE, `drive.file` scope, offline access, encrypted state cookie;
- return-to safety against open redirects;
- the Drive-connected rule;
- API security headers.

**Coverage given up:** the database-dependent behaviour is no longer covered automatically. That includes:
- the callback;
- sign-out revocation;
- Drive disconnect;
- deactivated users;
- bootstrap admin;
- the CSRF and admin checks.

All of these passed (73/73) against a manually created test database before the tests were removed. Verify them by hand against a dev database after significant changes.

## 6. Verification

- API: `uv run pytest` → 42 passed. `uv run ruff check .` and `uv run ruff format --check .` are clean.
- Web app: `pnpm exec tsc --noEmit`, `pnpm lint` and `pnpm build` pass.
- Before the database tests were removed, the full suite passed (73) against a test database built by hand from `schema.sql`, including:
  - the new sign-out revocation;
  - the Drive-disconnect failure paths;
  - the bootstrap-admin and deactivated-user rules.
- The guard that refused non-`_test` databases was confirmed against an `amber_dev` database. It's no longer needed, because the destructive tests are gone.
