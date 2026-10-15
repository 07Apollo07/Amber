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

The agent searches indexed documents visible to the signed-in Amber user. When it needs more than indexed excerpts, `get_file` retrieves the indexed source using the Drive connection of the document owner, after checking the caller's Amber access to that document. The model receives at most 80,000 extracted characters.

The native Workspace tools use the signed-in user's Google credentials and the existing narrow `drive.file` grant. Drive browsing is limited to files selected for Amber or created by Amber; it does not expose the user's entire Drive. Available operations include metadata/content reads, supported Docs/Sheets exports, folder and file creation/upload, rename/move/copy/trash/restore/delete, descriptions/starring, sharing permissions, and Drive comments/replies. Public-link sharing is not offered. The standard Drive API does not provide comment assignment operations.

Docs tools can read bounded document structure (including tabs, styles, tables, and page elements) and propose allowlisted text, formatting, table, image, page-element, named-range, and tab updates. Sheets tools can read workbook metadata and bounded cell ranges with formulas/formatting; propose bounded value updates, appends and clears; or propose allowlisted native batch requests for formatting, layout, workbook settings, validation, filters, protections, charts, pivots, slicers, and tables. Exports create a separate Drive file rather than changing the native source.

Every Workspace mutation pauses at a durable LangGraph checkpoint until the signed-in user approves or rejects it in the existing chat approval interface. No new file-browser or embedded-editor UI is included. Docs updates use the Docs API's required revision control. The Sheets API has no equivalent atomic revision check; Amber compares the reviewed workbook timestamp and affected cell values immediately before writing, but a concurrent edit could still race that final check. File and range reads/uploads are bounded by configured limits.

For multi-step or long-running requests, the agent uses a checkpointed task pad: it creates a plan before tool work, updates task statuses as work progresses, and receives the current plan on each model turn. The existing chat Queue displays the plan live and restores it when a conversation is reopened. Simple requests do not require a plan.

The agent can also choose to render generative UI when it improves an answer. Its available visual tools create validated charts, tables, KPI cards, comparisons, timelines, and source cards from user-provided or tool-retrieved data. Visuals stream into the existing chat and are restored from conversation checkpoints. The renderer supports only these app-owned components; it does not execute model-generated code. Visual selection is the agent's decision rather than a prompt-keyword trigger.

When `AMBER_LITELLM_BASE_URL` is configured, the chat's AI Elements model selector lists model IDs from LiteLLM's `/v1/models` endpoint. A selected model is validated against that list and used for the request; without LiteLLM, Amber continues to use `AMBER_AGENT_MODEL_NAME`.

Enable the **Google Drive API**, **Google Docs API**, and **Google Sheets API** in the Google Cloud project used by Amber's OAuth client. The `drive.file` OAuth scope continues to support only selected and Amber-created files; no broader Drive scope is requested. New Docs, Sheets, folders, uploads, and exports are created in the user's Drive or the selected destination. If durable checkpointing is unavailable, the agent disables all Workspace write tools rather than offering unresumable approvals.

| Endpoint | Purpose |
|---|---|
| `GET /api/auth/google/start?return_to=&reconnect=` | Start sign-in. `reconnect=true` forces the consent screen to re-grant Drive. |
| `GET /api/auth/google/callback` | Google redirect target. |
| `POST /api/auth/logout` | Sign out of this browser. |
| `POST /api/auth/logout-all` | Revoke every session for the account. |
| `POST /api/auth/google/disconnect` | Revoke the Drive grant at Google and delete the stored token. |
| `GET /api/me` | Current user, role and Drive status. |

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
