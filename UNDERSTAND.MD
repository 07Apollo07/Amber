# Understanding the Amber codebase

A reading order for the whole repo. Read it in layers: each layer only uses things from the layers before it, so you never meet a name you haven't seen yet.

There are about 4,500 lines of our own code; the rest is generated or third-party. **Skip entirely:**
- `ui/components/ui/*`, the generated shadcn components;
- `uv.lock` and `pnpm-lock.yaml`;
- `report.md`, a past audit.

## The map

```
 0. ORIENT        README.md ──► PLAN.md (Decisions table + Phase 2) ──► api/schema.sql
                                                                          │ (16 tables; read
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
 5. DRIVE &       api/amber/models.py        (drive_connected)
    DOCUMENTS          ▼
                  api/amber/util/drive.py    (get_drive_credentials → build_drive_service,
                       │                      upload_file_to_drive, fetch_drive_permissions)
                       ├──► api/amber/api/drive.py      list_drive_files, import_drive_files
                       └──► api/amber/api/documents.py  list / upload / delete
                                 ▼
                       api/amber/ingest/pipeline.py  process_document_upload
                                 ├──► ingest/parser.py   (parse_document)
                                 ├──► ingest/chunker.py  (chunk_document_blocks)
                                 ├──► ingest/embedder.py (generate_embeddings, Gemini)
                                 └──► repository: upsert_document, set_document_access, insert_chunk
                  UI side: ui/components/upload/drive-picker-panel.tsx, ui/components/profile/profile-page.tsx
                       │
 6. NOT WIRED     repository.py from hybrid_search_chunks (~line 429) on: collections, tags,
    UP YET             conversations, query_traces, settings. The SQL exists; no route calls it yet.
                  ui/components/search/* and ui/components/admin/*: UI only, empty data.
                       │
 7. TESTS         api/tests/*: short and readable; they confirm what each module promises.
```

## How to read each stage

### 0–1. Orient and foundations (about 30 minutes)
- **`api/schema.sql`:** find how `documents` → `document_access` → `chunks` connect. Almost everything later fills or queries those three tables, and `document_access` decides who can see what.
- **`api/amber/util/config.py`:** every setting comes from here. It reads `AMBER_*` variables, plus `GOOGLE_APPLICATION_CREDENTIALS`.
- **`api/amber/util/db.py`:** four small functions. Every query in the app goes through `fetch_one`, `fetch_all` or `execute`.
- **`api/amber/repository.py`:** read the first ~200 lines (users, OAuth tokens, signed-out sessions, audit log). For the rest, skim the function names only.

### 2. The app
- **`api/main.py`:** `create_app()` is the root of the backend. It starts Firebase, adds the security-headers middleware, and registers the four routers (`auth`, `me`, `documents`, `drive`).
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
Start from the user's action:
- **Picking Drive files** in the web app calls `import_drive_files` in `api/amber/api/drive.py`.
- **Uploading from the computer** calls `upload_document` in `api/amber/api/documents.py`, which hands off to `process_document_upload` in `api/amber/ingest/pipeline.py`.

Read `process_document_upload` in order:
1. save the file to the user's Drive (`util/drive.py`);
2. create the document row;
3. set who can access it (from Drive's sharing, or the chosen sharing option);
4. parse the file into text (`parser.py`);
5. split it into chunks (`chunker.py`);
6. create an embedding for each chunk with Gemini (`embedder.py`);
7. store the chunks.

### 6. Not wired up yet
`hybrid_search_chunks` and everything after it in `repository.py` (collections, tags, conversations, query traces, settings) has SQL but no routes yet. The Search and Admin screens in the web app show empty states.

### 7. Tests
`api/tests/` is short. Read it last to confirm what each module promises. None of the tests touch a database or the network.

## Known issues to keep in mind while reading

Two upload bugs have been fixed: the pipeline returned an undefined `external_id`, and it called a `repository.get_user` that didn't exist. These remain:

1. **Drive search can be manipulated.** `list_drive_files` puts the user's search text straight into the Drive query (`name contains '{q}'`). A search containing `'` changes the query.
2. **The Drive permission differs from the plan.** It's now `drive.readonly`, which reads the user's whole Drive. Google treats that as a restricted scope needing a security assessment (CASA) before public release. `PLAN.md` chose `drive.file` to avoid exactly that.
3. **Several database connections per request.** `current_user` opens its own connection, and uploads open another inside the pipeline. The upload's audit row is committed on a different connection from the document itself.
