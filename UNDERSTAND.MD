# Understanding the Amber codebase

A reading order for the whole repo. Read it in layers: each layer only uses things from the layers before it, so you never meet a name you haven't seen yet.

There are about 11,000 lines of Python in `api/` plus the Next.js app in `ui/`; the rest is generated or third-party. **Skip entirely:**
- `ui/components/ui/*` and `ui/components/ai-elements/*`, the generated shadcn and AI Elements components;
- `.agents/` and `.claude/skills/`, tooling for coding assistants;
- `uv.lock` and `pnpm-lock.yaml`;
- `report.md`, a past audit.

## The map

```
 0. ORIENT        README.md ──► DECISION.MD ──► api/schema.sql
                                                                          │ (20 tables; read
                                                                          │  users, oauth_tokens,
                                                                          ▼  documents, chunks first)
 1. BACKEND       api/amber/util/config.py   (every setting the API reads)
    FOUNDATIONS        │
                       ▼
                  api/amber/util/db.py        (connect, fetch_one, fetch_all, execute)
                       │
                       ▼
                  api/amber/repository.py     (ALL SQL; read only the first ~200 lines now:
                       │                       users, tokens, sessions, audit)
                       ▼
 2. THE APP       api/main.py  ── create_app() wires routers, middleware, Firebase start-up
                       │
                       ▼
                  api/amber/util/security.py  (cookies, CSRF, current_user, require_admin)
                       ├──► util/net.py       (client_ip)
                       └──► util/ratelimit.py (limit)
                       │
 3. SIGN-IN       api/amber/api/auth.py
    (main flow)        google_start ─────────► util/google_oauth.py  (authorization_url, new_pkce_pair)
                       google_callback ──┬───► google_oauth.exchange_code / verify_id_token
                                         ├───► util/firebase.py      (sign_in_with_google, create_session_cookie)
                                         ├───► util/crypto.py        (encrypt_token: refresh token at rest)
                                         ├───► _upsert_user ─► repository (users)
                                         └───► util/audit.py         (record)
                       logout / logout-all / disconnect_drive
                  api/amber/api/me.py  (what the web app learns about the user)
                       │
 4. WEB APP       ui/next.config.ts  (/api/* rewrite → the API, so cookies stay first-party)
    SIGN-IN            ▼
                  ui/proxy.ts  (route guard + CSP) ──► ui/lib/auth-paths.ts
                       ▼
                  ui/lib/session.ts (getSession → GET /api/me) ──► ui/app/(app)/layout.tsx
                       ▼                                              ▼
                  ui/app/(auth)/login/page.tsx              ui/lib/session-context.tsx (useSession)
                       ▼
                  ui/lib/api.ts  (apiPost/apiDelete + CSRF header)
                       │
 5. DRIVE &       api/amber/models.py        (drive_connected and the other scope checks)
    DOCUMENTS          ▼
                  api/amber/util/drive.py    (get_drive_credentials → build_drive_service,
                       │                      mint_picker_token,
                       │                      upload_file_to_drive, fetch_drive_permissions)
                       ├──► api/amber/api/drive.py      picker_token, import_drive_files
                       └──► api/amber/api/documents.py  list / upload / organize / access / delete
                                 ▼
                       api/amber/ingest/pipeline.py  process_document_upload
                                 ├──► ingest/settings.py (admin-tunable chunk size and upload limit)
                                 ├──► ingest/parser.py   (parse_document)
                                 ├──► ingest/chunker.py  (chunk_document_blocks)
                                 ├──► ingest/embedder.py (generate_embeddings, Gemini)
                                 └──► repository: upsert_document, set_document_access, insert_chunk
                  UI side: ui/components/upload/drive-picker-panel.tsx, ui/components/profile/profile-page.tsx
                       │
 6. KEEPING IN    api/amber/util/drive_sync.py  (ensure_drive_watch, process_drive_changes, reindex_due_files)
    SYNC               ▲
                  api/amber/api/drive.py: /webhook, /sync/reindex-due, /sync/renew  (Cloud Scheduler hits these)
                       │
 7. SEARCH &      repository.hybrid_search_chunks  (access filter + vector + full-text, one query)
    THE AGENT          ▼
                  api/amber/agent/graph.py   (LangGraph agent, system prompt, checkpointer)
                       ├──► agent/tools.py   (search, get_file, Drive / Docs / Sheets tools with approvals)
                       ├──► agent/trace.py   (what query_traces records)
                       └──► agent/settings.py
                  api/amber/api/agent.py     (/stream, /chat, conversations, /live voice WebSocket)
                  api/amber/api/collections.py
                  UI side: ui/components/search/* (chat, quick search, trace panel, citations, Opal sidekick)
                       │
 8. ADMIN         api/amber/api/admin.py  (users, documents, settings, traces, audit, analytics)
                  UI side: ui/components/admin/*
                       │
 9. OBSERVABILITY api/amber/util/posthog.py, posthog_logs.py  (optional; off without a project token)
                       │
10. TESTS & EVAL  api/tests/* (196 tests, no database or network) and api/eval/run_ragas.py
```

## How to read each stage

### 0–1. Orient and foundations (about 30 minutes)
- **`api/schema.sql`:** find how `documents` → `document_access` → `chunks` connect. Almost everything later fills or queries those three tables, and `document_access` decides who can see what.
- **`api/amber/util/config.py`:** every setting comes from here. It reads `AMBER_*` variables, plus `GOOGLE_APPLICATION_CREDENTIALS`.
- **`api/amber/util/db.py`:** four small functions. Every query in the app goes through `fetch_one`, `fetch_all` or `execute`.
- **`api/amber/repository.py`:** read the first ~200 lines (users, OAuth tokens, signed-out sessions, audit log). For the rest, skim the function names only.

### 2. The app
- **`api/main.py`:** `create_app()` is the root of the backend. It starts Firebase, PostHog and the agent's Postgres checkpointer, adds the security-headers middleware, and registers the seven routers (`auth`, `me`, `documents`, `drive`, `collections`, `agent`, `admin`).
- **`api/amber/util/security.py`:** read `current_user` closely, because nearly every route depends on it. It checks the session cookie, then loads the user and their role from Postgres. Also note `require_csrf`, which every state-changing request needs.

### 3. Sign-in (the most important flow)
Open `api/amber/api/auth.py` and follow `google_callback` from top to bottom, opening each helper as it's called. That one function covers:
1. checking the `state` and `nonce` values (protection against forged or replayed sign-ins);
2. exchanging the code with PKCE and verifying Google's ID token;
3. signing the user in to Firebase and creating the session cookie;
4. encrypting the Drive refresh token before it's stored (`crypto.py`);
5. creating or updating the user (`_upsert_user`) and recording the login (`audit.py`).

Then read `logout`, `logout_all` and `disconnect_drive`, and finally `api/amber/api/me.py`.

### 4. The web app's half of sign-in
Read the files in the order a page load uses them:
1. `ui/next.config.ts` sends `/api/*` to the API;
2. `ui/proxy.ts` redirects signed-out visitors to `/login`;
3. `ui/lib/session.ts` asks `/api/me` who's signed in;
4. `ui/app/(app)/layout.tsx` provides that user to every page through `ui/lib/session-context.tsx`.

`ui/lib/api.ts` is how buttons call the API: it adds the CSRF header.

### 5. Drive and documents
Sign-in asks Google for one Drive scope (`SCOPES` in `util/google_oauth.py`): `drive.file`, for files the user picks or Amber creates. The Picker token (`mint_picker_token`) and the agent's Drive tools use the same scope. `drive.readonly` is no longer requested.

Start from the user's action:
- **Picking Drive files** in the web app: the browser asks `picker_token` for a short-lived `drive.file` token, opens Google's Picker, then sends the picked IDs to `import_drive_files` in `api/amber/api/drive.py`.
- **Folders** can be browsed in the Picker but not selected as a whole: `drive.file` can't list a folder's contents. `POST /api/drive/folder-files` and `drive.list_folder_files` are still in the code but disabled (the endpoint always returns 409, and `can_import_folders` always returns False). The browser imports picked files in batches of 5.
- **Uploading from the computer** calls `upload_document` in `api/amber/api/documents.py`, which hands off to `process_document_upload` in `api/amber/ingest/pipeline.py`.

Read `process_document_upload` in order:
1. save the file to the user's Drive (`util/drive.py`);
2. create the document row;
3. set who can access it (from Drive's sharing, or the chosen sharing option);
4. parse the file into text (`parser.py`);
5. split it into chunks (`chunker.py`);
6. create an embedding for each chunk with Gemini (`embedder.py`);
7. store the chunks.

### 6. Keeping in sync with Drive
Read `util/drive_sync.py` with `DECISION.MD` §8 beside it. `ensure_drive_watch` registers a Drive change channel, `process_drive_changes` handles a webhook by refreshing permissions at once and queueing the content for re-indexing, and `reindex_due_files` (called by Cloud Scheduler every minute) re-indexes files that have been quiet for 5 minutes. The queue is the `drive_pending_reindex` table, not in-process timers.

### 7. Search, the agent and collections
`repository.hybrid_search_chunks` is the one query to understand: it applies the access list, vector search and full-text search together. `agent/graph.py` builds the LangGraph agent, and `agent/tools.py` holds its tools. Every tool that changes the user's Workspace goes through `_approved_operation`, which pauses for approval. `api/amber/api/agent.py` exposes streaming chat, conversations and the `/live` WebSocket that relays Opal voice sessions to Gemini Live. Collections (`api/amber/api/collections.py`) group documents and can share them to members as Drive viewers.

### 8. Admin
`api/amber/api/admin.py` serves the admin screens: users and roles, all documents, indexing settings, query traces, the audit log (with CSV export) and analytics. Every route needs `require_admin`.

### 9. Observability
PostHog is optional. `util/posthog.py` creates the client (and fails fast in dev if it isn't configured), and `util/posthog_logs.py` exports operational logs over OTLP. Both stay off unless `AMBER_POSTHOG_API_KEY` and `AMBER_POSTHOG_HOST` are set.

### 10. Tests and evaluation
`api/tests/` holds 196 tests. Read them last to confirm what each module promises. None touch a database or the network. `api/eval/run_ragas.py` is separate: it scores the agent's answers against `golden_dataset.json` with RAGAS and needs live model access.

## Known issues to keep in mind while reading

Fixed since the last version of this guide: the upload pipeline's undefined `external_id` and missing `repository.get_user`, and the Drive search injection (`list_drive_files` no longer exists; the agent's Drive search escapes quotes through `_drive_query_literal` in `agent/tools.py`). These remain:

1. **Leftover folder-import code.** The `drive.readonly` scope was removed, but `POST /api/drive/folder-files`, `drive.list_folder_files`, `can_import_folders` (and the `can_import_folders` field on `/api/me`) and their tests remain, all disabled. Some comments still mention the old scope (`api/amber/util/drive.py`, `api/amber/agent/tools.py`). They can be deleted together when convenient.
2. **Several database connections per request.** `current_user` opens its own connection, separate from the one `get_db` gives the route, and uploads open another inside the pipeline. The upload's audit row is committed on a different connection from the document itself.
3. **The upload limit isn't consistent.** The admin setting defaults to 50 MB and accepts up to 200, but Cloud Run and the Next.js proxy cap request bodies at about 32 MB (`ui/next.config.ts`). See `DEPLOY.MD` §3.
4. **Voice has two descriptions.** `api/README.md` describes both a direct Gemini Live relay and a LiteLLM `/v1/realtime` relay. The code in `api/amber/api/agent.py` implements the direct relay.
