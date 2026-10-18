# Amber API

FastAPI backend for Amber. Phase 2 covers authentication: Google sign-in with the Drive permission on one consent screen, Firebase session cookies, and encrypted storage of the Drive refresh token.

Postgres is accessed with **psycopg2** with one connection per request (`amber/util/db.py`). All SQL is hand-written and parameterized in `amber/repository.py`. There is no ORM, and the app never creates or alters tables. You create them in Postgres yourself; `schema.sql` is the reference definition of the tables the code expects.

## How sign-in works

```
browser ──GET /api/auth/google/start──▶ API ──303──▶ Google consent (openid email profile drive.file,
                                                     PKCE S256, state, nonce, access_type=offline)
Google ──GET /api/auth/google/callback?code&state──▶ API
   1. checks state against the encrypted, 10-minute, single-use state cookie
   2. exchanges the code (client secret + PKCE verifier) and verifies the Google ID token
      (signature, audience, issuer, expiry, nonce, email_verified)
   3. envelope-encrypts the refresh token (Cloud KMS key, AES-256-GCM, bound to the user id)
   4. signs in to Firebase server-side (signInWithIdp) and mints a 5-day session cookie
   5. sets the session (HttpOnly, Secure, SameSite=Strict) and CSRF cookies, then lands on the app
```

No Google or Firebase token ever reaches browser JavaScript. Every request verifies the session cookie with Firebase (including revocation), then loads the user and role from Postgres. State-changing requests need the `X-Amber-CSRF` header to match the CSRF cookie, and must come from the app's own origin.

## Agent document workspace

The agent searches indexed documents visible to the signed-in Amber user. When it needs more than indexed excerpts, `get_file` retrieves the indexed source using the caller's current Google Drive connection, after checking the caller's Amber access to that document. The model receives at most 80,000 extracted characters.

The native Workspace tools use the signed-in user's Google credentials and the existing narrow `drive.file` grant. Drive browsing is limited to files selected for Amber or created by Amber; it does not expose the user's entire Drive. Available operations include metadata/content reads, supported Docs/Sheets exports, folder and file creation/upload, rename/move/copy/trash/restore/delete, descriptions/starring, sharing permissions, and Drive comments/replies. Public-link sharing is not offered. The standard Drive API does not provide comment assignment operations.

Docs tools can read bounded document structure (including tabs, styles, tables, and page elements) and propose allowlisted text, formatting, table, image, page-element, named-range, and tab updates. Sheets tools can read workbook metadata and bounded cell ranges with formulas/formatting; propose bounded value updates, appends and clears; or propose allowlisted native batch requests for formatting, layout, workbook settings, validation, filters, protections, charts, pivots, slicers, and tables. Exports create a separate Drive file rather than changing the native source.

Every Workspace mutation pauses at a durable LangGraph checkpoint until the signed-in user approves or rejects it in the existing chat approval interface. No new file-browser or embedded-editor UI is included. Docs updates use the Docs API's required revision control. The Sheets API has no equivalent atomic revision check; Amber compares the reviewed workbook timestamp and affected cell values immediately before writing, but a concurrent edit could still race that final check. File and range reads/uploads are bounded by configured limits.

For multi-step or long-running requests, the agent uses a checkpointed task pad: it creates a plan before tool work, updates task statuses as work progresses, and receives the current plan on each model turn. The existing chat Queue displays the plan live and restores it when a conversation is reopened. Simple requests do not require a plan.

The agent can also choose to render generative UI when it improves an answer. Its available visual tools create validated charts, tables, KPI cards, comparisons, timelines, and source cards from user-provided or tool-retrieved data. Visuals stream into the existing chat and are restored from conversation checkpoints. The renderer supports only these app-owned components; it does not execute model-generated code. Visual selection is the agent's decision rather than a prompt-keyword trigger.

When `AMBER_LITELLM_BASE_URL` is configured, the chat's AI Elements model selector lists model IDs from LiteLLM's `/v1/models` endpoint. A selected model is validated against that list and used for the request; without LiteLLM, Amber continues to use `AMBER_AGENT_MODEL_NAME`.

The Opal voice sidekick (`/api/agent/live` WebSocket) does not use LiteLLM. The API opens a Gemini Live session with Google AI Studio directly, using `AMBER_GEMINI_LIVE_API_KEY` (or `AMBER_GEMINI_API_KEY` when that is empty) and `AMBER_GEMINI_LIVE_MODEL`. The API owns the system prompt and tools, takes the chat context from the browser as untrusted reference material, and relays 16 kHz microphone audio in and 24 kHz speech out. The key never reaches the browser.

Opal's Gemini Live voice session uses the same LiteLLM proxy through an authenticated API WebSocket relay at `/v1/realtime`. It defaults to the `gemini-3.8-live` model alias; set `AMBER_LITELLM_BASE_URL` and override `AMBER_AGENT_LIVE_MODEL_NAME` only if your LiteLLM deployment uses a different alias. The browser reads voice availability from `/api/agent/live/config`, while LiteLLM credentials remain server-side. Voice suggestions only populate Amber's chat composer and never submit agent requests or approve Workspace changes.

Indexed Drive files are owned in Amber by their Google Drive owner; the person who first imported a file is retained only as attribution. Amber's file-management views separate **My files** from **Shared with me**, and a document can belong to multiple collections. Sharing a collection adds its members as Drive viewers on every current file and on files later added to that collection. Amber tracks only the Drive permission grants it created and removes those grants when no collection still needs them; direct grants made elsewhere are preserved. Collection members can organize files in a shared collection, but Drive itself remains authoritative for file access. This release supports files in My Drive only; Shared Drives, Drive group membership resolution, and public-link access are not supported.

For permission freshness, Amber starts a per-user Google Drive Changes API watch after a successful Drive import and when the Data page loads tracked Drive files. The unauthenticated `/api/drive/webhook` endpoint verifies Google's channel ID, resource ID, and a random channel token before reading change pages and refreshing supported user/domain ACLs. It advances the saved cursor only after a complete successful reconciliation; lost access removes only the affected signed-in user's grant. Watches are renewed as users return to Amber or when a notification arrives near expiry, so deploy `AMBER_PUBLIC_BASE_URL` with a valid HTTPS origin. The Drive Changes API supports the existing `drive.file` scope; no broader OAuth scope is added.

Enable the **Google Drive API**, **Google Docs API**, and **Google Sheets API** in the Google Cloud project used by Amber's OAuth client. The `drive.file` OAuth scope continues to support only selected and Amber-created files; no broader Drive scope is requested. New Docs, Sheets, folders, uploads, and exports are created in the user's Drive or the selected destination. If durable checkpointing is unavailable, the agent disables all Workspace write tools rather than offering unresumable approvals.
## Drive permission synchronization

After Drive is connected or a file is imported, Amber registers a Google Drive Changes API watch. Google sends notifications to `POST /api/drive/webhook`; each notification is authenticated against its stored channel, then Amber reads the user's changes feed and refreshes permissions for already-indexed files. The webhook uses Drive's `drive.file` scope and synchronizes direct user and domain grants. Group, link-wide, and Shared Drive permissions are not synchronized.

Apply `schema.sql` to add the `drive_sync_state` table before deploying this feature. Set `AMBER_PUBLIC_BASE_URL` to the public HTTPS origin that routes `/api/drive/webhook` to this API. Drive watch channels expire, so configure `AMBER_DRIVE_SYNC_ADMIN_SECRET` and a daily Cloud Scheduler job that sends:

```http
POST /api/drive/sync/renew
X-Amber-Drive-Sync-Secret: <configured secret>
```

The renewal endpoint returns counts of renewed and failed channels. A failed permission fetch does not replace the current ACL or advance that user's change cursor; Google can retry the webhook.

| Endpoint | Purpose |
|---|---|
| `GET /api/auth/google/start?return_to=&reconnect=` | Start sign-in. `reconnect=true` forces the consent screen to re-grant Drive. |
| `GET /api/auth/google/callback` | Google redirect target. |
| `POST /api/auth/logout` | Sign out of this browser. |
| `POST /api/auth/logout-all` | Revoke every session for the account. |
| `POST /api/auth/google/disconnect` | Revoke the Drive grant at Google and delete the stored token. |
| `GET /api/me` | Current user, role and Drive status. |
| `POST /api/drive/webhook` | Receive Google Drive change notifications (Google only). |
| `POST /api/drive/sync/renew` | Renew expiring Drive watch channels (scheduler secret required). |

## Local development

```bash
cp .env.example .env              # fill in the values
uv sync
uv run python main.py                # http://127.0.0.1:8000, auto-reloads when AMBER_ENV=dev
```

Firebase Admin (session cookies, revocation) needs Google credentials, so the API won't start without them. Set `GOOGLE_APPLICATION_CREDENTIALS` in `api/.env` to your service-account key file. A relative path is resolved against the `api` folder. The service account needs the Firebase Authentication Admin role. Key files are git-ignored; never commit one.

Then run the web app (`ui`, `pnpm dev`) and open http://localhost:3000. The web app proxies `/api/*` here, so cookies stay first-party.

Over plain-http localhost, cookies drop the `__Host-` prefix because browsers only accept it over https. They are still Secure, HttpOnly and SameSite.

## Docker Compose

From the `api` folder, start the API with:

```bash
docker compose up --build
```

Set `GOOGLE_APPLICATION_CREDENTIALS` in `.env` to the service-account key's filename in
`api/`. Compose mounts that file read-only at `/run/secrets/google-credentials.json`; it is not
copied into the image. The API's `AMBER_DATABASE_DSN` must point to a database reachable from
the container. For a database running on the host, use `host.docker.internal` instead of
`127.0.0.1` in the DSN. This Compose setup runs only the API; it does not create a database or
initialize its schema.

## Tests

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The tests never connect to a database or call Google or Firebase, so they're safe to run anywhere, at any time. They cover crypto, config validation, client-IP resolution, the sign-in redirect, return-to safety and security headers. Tests that wrote to a database or depended on timing were removed on purpose.
