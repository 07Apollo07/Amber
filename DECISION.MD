# Amber: Design Decisions

This file records the main design decisions behind Amber: what we chose, why, and what it costs us. Each decision lists where it lives in the code, so it can be checked against the implementation. The last section lists known gaps between these decisions and the current code.

**Contents**

1. [Guiding principles](#1-guiding-principles)
2. [Access control: permissions come from Google Drive](#2-access-control-permissions-come-from-google-drive)
3. [Database permissions and least privilege](#3-database-permissions-and-least-privilege)
4. [Authentication and sessions](#4-authentication-and-sessions)
5. [Protecting Google credentials](#5-protecting-google-credentials)
6. [Web security: CSRF, CSP and headers](#6-web-security-csrf-csp-and-headers)
7. [A stateless API](#7-a-stateless-api)
8. [Keeping in sync with Drive](#8-keeping-in-sync-with-drive)
9. [Data access: hand-written SQL, no ORM](#9-data-access-hand-written-sql-no-orm)
10. [Retrieval and RAG](#10-retrieval-and-rag)
11. [The agent: human approval for every change](#11-the-agent-human-approval-for-every-change)
12. [Hosting and deployment](#12-hosting-and-deployment)
13. [Auditing and abuse protection](#13-auditing-and-abuse-protection)
14. [Known gaps and follow-ups](#14-known-gaps-and-follow-ups)

---

## 1. Guiding principles

1. **Never show a user a document they can't open.** Every other decision gives way to this one.
2. **Google Drive is the source of truth** for files and for who may see them. Amber follows Drive and never keeps a second, competing permission model.
3. **Least privilege everywhere:** OAuth scopes, database roles, cloud service accounts and agent actions.
4. **Defense in depth.** No single check is the only thing standing between a user and someone else's data.
5. **Stateless, scale-to-zero services.** Any instance can serve any request, and idle instances cost nothing.
6. **Explicit over magic.** Hand-written SQL, a schema applied by hand, and decisions written down here.

---

## 2. Access control: permissions come from Google Drive

**Decision.** Each indexed document has an access list (`document_access`) copied from the file's Google Drive sharing settings. A user may read a document only if one of their principals matches an entry:

- `user:<their email>`, or
- `domain:<their Google Workspace domain>` (the `hd` claim from Google sign-in).

**Why.**
- Companies already manage sharing in Drive. Asking them to rebuild it in Amber would be costly, and the two copies would drift apart.
- When access follows Drive, each employee gets exactly the information Drive already lets them open: need-to-know by default.

**How it works.**
- **On import**, Amber reads the file's Drive permissions (`drive.fetch_drive_permissions`) and writes them to `document_access` with `origin = 'drive_sync'` (`api/amber/api/drive.py`, `api/amber/ingest/pipeline.py`).
- **On change**, Drive webhooks re-read the permissions of changed files and replace the access list (`drive_sync.process_drive_changes`). A trashed or removed file falls back to owner-only access.
- **At query time**, two independent checks filter by the access list, both inside the search query, so text from a blocked document is never read, never sent to the model and never returned:
  1. **An explicit `EXISTS` on `document_access`** in every branch of the search SQL (`repository.hybrid_search_chunks`).
  2. **Postgres Row-Level Security** on `documents`, `chunks` and `document_access`, with **`FORCE ROW LEVEL SECURITY`**, so the policies bind the table owner too (`schema.sql`, `documents_access_policy`).

  Either check alone blocks a leak. The explicit check still holds when RLS is skipped (a superuser connection) or relaxed (the trusted-sync flag set earlier in the transaction). RLS still holds if a future query forgets the explicit check.
- **Per-transaction identity:** before each scoped query the API sets `app.user_email` and `app.user_domain` with `set_config(..., true)` (`repository.set_app_user_context`). The `true` makes them transaction-local, so one request's identity can never leak into another request on the same connection.
- **Single-document access** (opening, previewing, or the agent's `get_file`) goes through the same policy, which protects against guessing document IDs.

**Trade-offs.**
- Only `user` and `domain` principals are supported. Google Groups, shared drives and "anyone with the link" aren't mapped yet (see §14).
- The `drive.file` scope means Amber only sees files the user picked or that Amber created, not the whole Drive (see §4).
- Permission changes arrive by webhook, so there is a short delay between a change in Drive and the change in Amber.

---

## 3. Database permissions and least privilege

**Decision.** The application never owns or alters its own schema, and it connects with a role that can do only what the app needs.

| Role | Purpose | Rights |
|---|---|---|
| `amber_migrator` | Owns the schema; applies `schema.sql` by hand | DDL |
| `amber_app` | The API at runtime | Data changes on app tables only; **`INSERT` only on `audit_log`**; RLS enforced; no `BYPASSRLS` |

**Why.**
- If the API is compromised, it can't drop tables, change the schema, turn off RLS or rewrite history.
- **The audit log is append-only by construction.** `amber_app` has `INSERT` on `audit_log` but no `SELECT`, `UPDATE` or `DELETE`, so even a compromised API can't erase its tracks.
- **RLS only applies to roles that don't own the table.** Splitting the owner (`amber_migrator`) from the runtime role (`amber_app`) is what makes the RLS policies in §2 actually take effect.

**Supporting choices.**
- **Schema applied by hand.** `schema.sql` is idempotent (`IF NOT EXISTS`, `DROP POLICY IF EXISTS`) and is reviewed and applied by the project owner. There is no migration framework and no automatic DDL at start-up, so production structure changes only happen deliberately.
- **Grants are conditional.** `GRANT`s run only `IF EXISTS` the role, so the same file works on a developer database that doesn't have the role yet.
- **One database per environment.** `amber` and `amber_dev` are separate, and dev and tests never point at production.
- **Deletes cascade.** Removing a user removes their tokens, documents, chunks and conversations through foreign keys, not through application code that might miss a table.

**Trade-offs.**
- Every schema change is a manual step, so deploys must be coordinated with the schema owner.
- The planned separate ingestion role (`amber_worker`, limited to documents and chunks) isn't created yet; ingestion runs as `amber_app` today.

---

## 4. Authentication and sessions

**Decision.**
- Users sign in with Google through a **server-side OAuth flow**, which also asks for the Drive permission on the same consent screen.
- The API then creates a **Firebase session cookie**. No Google or Firebase token is ever exposed to browser JavaScript.

**The flow** (`api/amber/api/auth.py`, `util/google_oauth.py`, `util/firebase.py`):
1. `/api/auth/google/start` redirects to Google with **PKCE (S256)**, a `state` value and a `nonce`, plus `access_type=offline`. These are stored in an encrypted, 10-minute, single-use cookie.
2. The callback checks `state`, exchanges the code using the client secret and the PKCE verifier, and verifies the ID token: signature, audience, issuer, expiry, `nonce` and `email_verified`.
3. The refresh token is encrypted (§5). The API signs in to Firebase server-side and mints a 5-day session cookie.
4. The session cookie is `HttpOnly`, `Secure` and `SameSite=Strict`, with the `__Host-` prefix over HTTPS (`security.cookie_names`).

**Each request** (`security.current_user`):
- Verifies the cookie with Firebase: signature, expiry and "sign out everywhere" revocation.
- Rejects cookies signed out on a single device. These are kept in `revoked_sessions` as a **SHA-256 hash, never the cookie itself**.
- Loads the user from Postgres and rejects deactivated accounts.

**Roles live in Postgres, not in tokens.** `require_admin` reads `users.role`, and client claims are never trusted. The first admins come from `BOOTSTRAP_ADMIN_EMAILS`, and only when that account is first created, so the variable can't be used later to promote an existing account.

**Narrow Drive scope.** Amber asks for `drive.file`: files the user picks in the Google Picker, plus files and folders Amber creates.
- It is least privilege, and it avoids Google's restricted-scope security assessment.
- Picker tokens are minted narrowed to `drive.file`, even if the stored grant is broader (`drive.mint_picker_token`).
- Indexing the whole Drive (`drive.readonly`) is deferred until Google's verification is done.

---

## 5. Protecting Google credentials

**Decision.** Google refresh tokens are **envelope-encrypted** before they reach the database (`api/amber/util/crypto.py`).

- **Per-token key.** Each token gets a fresh 256-bit data key, and the token is sealed with **AES-256-GCM**.
- **Wrapped data key.** The data key is wrapped by **Cloud KMS** in production. Dev and test can use a local key instead, and that fallback is refused when `env == prod`.
- **Bound to the user.** Both layers use the owning user's ID as additional authenticated data, so a ciphertext copied onto another user's row fails to decrypt.
- **Versioned format.** The blob is versioned and records the KMS key version, so keys can be rotated.
- **Disconnect revokes at Google.** Disconnecting Drive revokes the token at Google and deletes the stored copy.

**Why.** A database dump or a SQL-injection read gives an attacker nothing usable without access to the KMS key. KMS access is a separate IAM permission held only by the API's service account.

**Secrets.** OAuth client secret, Firebase key, Gemini key, cookie key, database DSN and the Drive sync secret all live in **Secret Manager**. They're mounted into Cloud Run at deploy time and never committed. The API authenticates to Google with its service account (Application Default Credentials), not with key files.

---

## 6. Web security: CSRF, CSP and headers

**One origin.** The browser only talks to the web app, which forwards `/api/*` to the API (`ui/next.config.ts`). The design depends on this:
- Cookies stay first-party, which is required for `__Host-` cookies and `SameSite=Strict`.
- The OAuth redirect is built from a single `AMBER_PUBLIC_BASE_URL`.

**CSRF** (`security.require_csrf`). Every state-changing request must pass two checks:
1. If an `Origin` header is present, it must equal the app's origin.
2. **Double-submit token:** a non-HttpOnly `amber_csrf` cookie must match the `X-Amber-CSRF` header. The comparison is constant-time.

**Content Security Policy** (`ui/proxy.ts`).
- A per-request **nonce** with `strict-dynamic` controls scripts.
- `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'` and `form-action 'self'` are set.
- Google domains are allowed only where the Picker needs them.
- `style-src 'unsafe-inline'` is a deliberate exception: Radix positions popovers with inline styles, which nonces can't cover.

**API response headers** (`main.py`): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store`, because every API response is per-user.

**Less exposure in production.** OpenAPI docs are disabled when `env == prod`.

**Route guard.** The web app's guard is optimistic only, a quick redirect to `/login`. The real check is always the API's (§4).

---

## 7. A stateless API

**Decision.** The API keeps no state in memory that a request depends on. Everything that has to outlive a request lives in Postgres, in a signed or encrypted cookie, or in a Google-managed service. Any Cloud Run instance can serve any request, instances can be killed at any time, and the service scales to zero.

| Concern | Where the state lives |
|---|---|
| Sign-in session | Firebase session cookie (signed), checked on every request |
| Per-device sign-out | `revoked_sessions` table |
| OAuth `state`, `nonce`, PKCE verifier | Encrypted, single-use, 10-minute cookie |
| User, role, account status | Postgres, loaded per request |
| Database connections | One per request, closed afterwards (`security.get_db`); uncommitted work is discarded |
| Agent conversations and paused approvals | LangGraph **Postgres checkpointer** (`AsyncPostgresSaver`) |
| Drive watch channels and change cursor | `drive_sync_state` |
| "File changed, wait 5 minutes" timers | `drive_pending_reindex` rows, not in-process timers |
| Recurring work | **Cloud Scheduler** calls HTTP endpoints, not background threads |

**Why.**
- Cloud Run starts and stops instances freely, and idle instances are billed. Stateless services make scale-to-zero safe and horizontal scaling trivial.
- A paused agent approval survives a deploy or a cold start, because its checkpoint is in Postgres.

**The Drive re-index debounce is the clearest example** (§8). The obvious design, "start a 5-minute timer when a webhook arrives", fails on Cloud Run, because the instance holding the timer may be gone in 5 minutes. Instead:
- each webhook pushes back a timestamp in Postgres;
- a scheduler call every minute processes files whose timestamp is more than 5 minutes old;
- work is claimed with a 15-minute lease using `FOR UPDATE SKIP LOCKED`, so overlapping runs never process the same file twice and a crashed run is retried.

**Exceptions (deliberate or temporary).**
- **Rate-limit counters are in memory, per instance** (§13). This is approximate by design and is meant to be backed by a global limit at the edge.
- **If Postgres is unreachable at start-up,** the agent falls back to an in-memory checkpointer, and its write tools are disabled (`main.py`). That instance's conversations would not survive a restart. See §14.

---

## 8. Keeping in sync with Drive

**Decision.** Use **Drive push notifications** (`changes.watch`) instead of polling. Treat each notification only as a **hint**: always read the authoritative changes feed.

- **Watching.** Each user has one watch channel (`drive_sync.ensure_drive_watch`). The page token, channel ID, resource ID and the **SHA-256 hash of a random channel token** are stored in `drive_sync_state`.
- **Webhook authentication.** The webhook is public, because Google must reach it. Each call must present a known channel ID, the matching resource ID, and a token whose hash matches, compared in constant time (`validate_notification`). Unknown callers get a 404.
- **Processing.** The API pages through `changes.list` from the stored cursor, de-duplicates file IDs, and updates permissions for indexed files. The cursor only advances after that work commits, so a failure means the batch is retried, never skipped.
- **Content re-indexing is debounced.** Each change to an indexed file upserts a row in `drive_pending_reindex` and resets `last_change_at`. Files go to re-indexing once **5 minutes pass with no change**, or **1 hour after the first change** if edits never stop. Both are configurable (`AMBER_DRIVE_REINDEX_QUIET_SECONDS`, `AMBER_DRIVE_REINDEX_MAX_WAIT_SECONDS`).
- **Skipping unchanged content.** Before re-embedding, the file's sha256 is compared with the stored hash. Permission-only or metadata-only changes cost one download, not a re-embed.
- **Edits during indexing aren't lost.** A row is deleted only if `last_change_at` is still the value seen when it was claimed. An edit made during indexing keeps the row for the next run.
- **Failures keep the old index.** A failed re-index keeps the old chunks searchable, marks the document `failed` with the reason, and retries up to 5 times. Any new change resets the retry count.
- **Renewal.** Drive channels expire, so a daily Scheduler job renews channels that expire within 24 hours. The cursor is kept, and the old channel is stopped only after the new one is saved.
- **Scheduler authentication.** Scheduler endpoints need a shared secret header (`X-Amber-Drive-Sync-Secret`), compared in constant time, with the secret stored in Secret Manager.

**Why debounce?** Google Docs fires notifications constantly while someone types. Re-embedding on each one would waste Gemini spend and database writes, while permission updates still need to be immediate. Splitting "permissions now" from "content when quiet" gives both.

---

## 9. Data access: hand-written SQL, no ORM

**Decision.** All SQL is hand-written and **parameterized** (`%(name)s` placeholders) in `api/amber/repository.py`, using psycopg2. Values are never formatted into SQL strings.

**Why.**
- The security-critical queries (RLS context, vector search, access checks, claim-with-lease) are short, explicit and reviewable in one file.
- An ORM would hide exactly the details that matter here: transaction-local settings, `FOR UPDATE SKIP LOCKED`, pgvector operators and RLS behavior.
- One file is one place to audit for injection.

**Trade-offs.** It means more boilerplate, and schema changes must be mirrored by hand in queries and in `schema.sql`.

---

## 10. Retrieval and RAG

- **Postgres for vectors as well as data.** pgvector (HNSW, cosine) sits next to the documents and access lists, so the access filter and the vector search run **in one query and one transaction**. A separate vector database would mean filtering after retrieval, or copying the access lists, which could drift.
- **Hybrid search.** Vector distance is combined with Postgres full-text search (`tsvector`, `ts_rank_cd`), so exact terms such as names, IDs and codes are found as well as similar meaning.
- **Models.** Gemini through the Google AI API on the **paid tier**, so prompts and documents aren't used for training. Answers use `gemini-2.5-flash` by default; embeddings use `gemini-embedding-001` at 1536 dimensions.
- **Swappable model provider.** An optional LiteLLM endpoint lets the chat use other models. The requested model is validated against LiteLLM's model list.
- **Traceability.** Query, rewritten query, retrieved and cited chunks, model, tokens and latency are recorded in `query_traces`, so every answer can be explained and audited.
- **Ingestion.** Content is checked by type and size (admin-configurable limit, 30 MB today). Google Docs, Sheets and Slides are exported to Office formats so they parse like uploads. Desktop uploads are saved to the uploader's Drive (`Amber Uploads` folder), so Drive becomes the file's home and the source of its sharing.

---

## 11. The agent: human approval for every change

**Decision.**
- The agent (LangGraph) may **read** what the user is allowed to read.
- **Every change to the user's Workspace pauses for explicit approval.** This covers file moves, sharing, comments, exports, and Docs and Sheets edits.

**How.**
- Write tools call LangGraph's `interrupt()` with a before/after preview (`agent/tools._approved_operation`). The pause is saved by the Postgres checkpointer, so an approval can wait through restarts.
- Docs edits use the Docs API's revision control.
- Sheets has no equivalent, so Amber re-checks the workbook timestamp and the affected cells just before writing. A concurrent edit could still race that last check.
- Public-link sharing isn't offered.
- If durable checkpointing isn't available, write tools are disabled entirely.
- **Generative UI is limited to app-owned components** (charts, tables, cards). The renderer never executes model-generated code.

**Why.** An LLM can be wrong or manipulated by content inside a document (prompt injection). Requiring approval keeps a person responsible for every change to company data.

---

## 12. Hosting and deployment

- **Two Cloud Run services:** `amber-web` (Next.js) and `amber-api` (FastAPI). The web service forwards `/api/*` to the API. Both run with `--min-instances 0`.
- **Separate service accounts** (`amber-api@…`, `amber-web@…`). Only the API's account can reach Cloud SQL, Firebase Admin, the KMS key and its secrets.
- **Cloud SQL** connection uses the Cloud SQL connector (`--add-cloudsql-instances`). Cloud Run is placed in the same region as the database.
- **Reproducible deploys.** `deploy/cloudrun.sh` builds both images with Cloud Build, refuses to deploy if any required secret has no value, and sets the secret list explicitly with `--set-secrets` on each deploy.
- **No load balancer yet.** It is deferred until there is a custom domain and paying customers. The path to it (global HTTPS load balancer plus Cloud Armor) changes only the front door.

---

## 13. Auditing and abuse protection

- **Audit log.** Sign-ins, sign-outs, Drive connections and disconnections, imports, sharing changes and admin actions are written to `audit_log` in the **same transaction** as the action, so an action and its audit record commit together or not at all. The table is append-only for the app role (§3).
- **Rate limiting.** Fixed-window limits per client IP on authentication and Picker endpoints (`util/ratelimit.py`). These are in memory per instance and approximate under concurrency, which is acceptable for a rate limit. Cloud Armor is the planned global layer.
- **Client IP that can't be spoofed.** `X-Forwarded-For` is only trusted when the request comes from a configured proxy (`AMBER_TRUSTED_PROXIES`), and it is walked from the right (`util/net.py`). Uvicorn's own proxy-header handling is turned off.

---

## 14. Known gaps and follow-ups

These are places where the code doesn't yet fully match the decisions above. Each one is a planned fix, not a reversal of the decision.

| Gap | Risk | Planned fix |
|---|---|---|
| Superusers and `BYPASSRLS` roles skip RLS even with `FORCE` | Search stays filtered by the explicit check, but other document queries (opening a document, listing) rely on RLS | Never connect the app as a superuser; add explicit checks to the other document queries |
| `count_hidden_chunks` reads `chunks` under RLS, so it can't see hidden chunks and always returns 0 | Wrong count once it's wired in | Rewrite it as a count over a security-definer function, or a separate role, before using it |
| `app.drive_sync = 'true'` lets trusted sync code see every document | Safe only while all SQL stays parameterized. A bug that lets user input set it would bypass RLS | Move sync work to a separate database role (`amber_worker`) instead of a session flag |
| The `amber_worker` role isn't created yet | Ingestion has the same rights as the API | Create it with rights limited to `documents`, `chunks` and `document_access` |
| The database DSN uses a password from Secret Manager | A static credential | Switch to Cloud SQL IAM database authentication |
| In-memory checkpointer fallback when Postgres is unreachable at start-up | That instance's conversations and approvals are lost on restart | Fail health checks rather than starting in a degraded mode |
| Rate limits are per instance | Limits multiply with the number of instances | Cloud Armor rate rules at the load balancer |
| The "N results hidden because of access" count (`count_hidden_chunks`) isn't wired into answers | No user-visible signal that results were filtered | Call it from search and show it in the trace panel |
| Only `user` and `domain` Drive principals are mapped | Files shared through Google Groups or shared drives may be under-shared in Amber (safe, but incomplete) | Resolve group membership through the Admin SDK |
| Webhooks need a public HTTPS `AMBER_PUBLIC_BASE_URL` | Drive sync can't run on plain `localhost` | Use a tunnel for local testing (documented in the README) |
