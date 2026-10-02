# Amber — Implementation Plan

## Context
Amber is an enterprise RAG web app. Users sign in with Google, index their uploads and Google Drive files, and ask questions answered by Gemini. Every answer cites its sources and comes with a trace, and **results never include a document the user isn't allowed to see**. The repo is empty right now (only `README.md` and `.gitignore`), so this is a greenfield build. We build the UI first, against a mocked API contract, and then put the real backend behind it.

### Decisions (from Q&A)
| Area | Decision |
|---|---|
| Layout | Top nav bar (`AMBER · Search · Upload · Admin(admin only) · avatar menu → Profile/Sign out`). Dark theme only, amber accent |
| Search | Two modes: **Quick** (one answer plus ranked sources) and **Chat** (multi-turn, streamed, history saved) |
| Search controls | Source filter (Upload/Drive/collection), file-type and date filters, source preview side panel, thumbs up/down feedback, traceability |
| Traceability | "How this answer was built" panel (query rewrite, retrieved chunks with vector/keyword/rerank scores, which ones were cited), an access audit note ("N results hidden: no access"), and a full admin trace log |
| Upload | Drag-and-drop local upload, Google Drive Picker, collections/tags, sharing on upload (private / specific users / my domain). **Every desktop upload is also saved to the uploader's Google Drive** (in an `Amber Uploads` folder). Drive then becomes the file's home and the source of its sharing |
| Admin | Users & roles, access & audit logs, analytics & settings, **plus Documents management** (in the original brief even though it wasn't ticked) |
| Profile | Account info, connected Google Drive, my documents and history |
| Roles | Admin / Member. Sign-in is open to anyone with a Google account (new users are Members). The first admin is seeded from the `BOOTSTRAP_ADMIN_EMAILS` env var |
| RAG / LLM | **LangChain** (LCEL) runs the RAG pipeline. Models are **Gemini through the Google AI (Gemini) API** using `langchain-google-genai`, on the **paid tier** (prompts and data aren't used for training). Answers use the latest Gemini Flash (Pro configurable), and embeddings are `gemini-embedding-001` at 1536 dims. There's no Vertex AI dependency, and the provider can be swapped through LangChain's `init_chat_model` |
| Auth | **Existing Firebase Auth project (cloud)**. Amber configures it but does not create it, and uses no local emulator |
| Database | **Existing Postgres already deployed in the cloud** (assumed Cloud SQL on GCP). Amber adds its own database, roles, and the pgvector extension to it, and does not provision a new instance |
| Hosting | GCP: Cloud Run (web, api, worker), GCS, Secret Manager, KMS, Cloud Tasks, Cloud Scheduler, connecting to the existing Firebase and Postgres |

## Existing infrastructure: prerequisites and setup
Firebase and Postgres already exist, so Amber **connects to them, configures them, and never re-creates them**. Do this once, before step 3 of the build order:

**Firebase Auth (cloud)**
- Enable the **Google** sign-in provider. Add the app domains (and `localhost` for dev) to **Authorized domains**.
- Make sure the Firebase project's GCP project has the OAuth consent screen configured with the `drive.file` scope, and create an OAuth **Web client** (client id/secret go in Secret Manager).
- `firebase-admin` in FastAPI authenticates with **Application Default Credentials** (the Cloud Run service account, `roles/firebaseauth.admin`), so no service-account JSON keys are needed. For local dev, use `gcloud auth application-default login` with impersonation of a dev SA.
- Recommended: a **separate Firebase project (or Identity Platform tenant) for dev/staging**, so test sign-ins never touch production users.

**Postgres (existing cloud instance)**
- Check the version (≥ 14) and that **pgvector ≥ 0.5** is available (HNSW). On Cloud SQL it's built in, so `CREATE EXTENSION vector;` is enough.
- Create a dedicated database `amber` (plus `amber_dev`/`amber_staging`, or a separate instance) so Amber is isolated from anything else on the instance. **Never point dev or tests at the prod DB.**
- Roles (least privilege):
  - `amber_migrator` owns the schema. Tables are created **manually** by the project owner (reference: `app/api/schema.sql`); the app never creates or alters them.
  - `amber_app` (API): DML on app tables, and INSERT-only on `audit_log`. RLS is enforced and it does not bypass RLS.
  - `amber_worker` (ingestion): write access to `documents`/`chunks`/`document_access` only.
- Connectivity:
  - The API connects with **psycopg2** to the **Cloud SQL Auth Proxy** sidecar on `127.0.0.1`. The proxy uses **private IP** (Cloud Run Direct VPC egress or a serverless VPC connector), TLS, and **IAM database authentication** (`--auto-iam-authn`), so there are no static DB passwords. The Cloud SQL Python connector doesn't support psycopg2.
  - If IAM auth isn't available on this instance, store passwords in Secret Manager and rotate them.
  - For local dev, use the Cloud SQL Auth Proxy to reach `amber_dev`.
- Backups/PITR: confirm they're already enabled on the existing instance (Amber doesn't manage that).

**Open items to confirm:** the GCP project id(s) for Firebase and Postgres, whether the Postgres instance is Cloud SQL (or AlloyDB/other), whether it has private IP, and whether a dev database or instance already exists.

## Repo layout (monorepo)
```
app/ui/        Next.js 16 (App Router, TS, Tailwind, shadcn/ui, TanStack Query, zod)
app/api/        FastAPI (Python 3.12, uv, psycopg2 with hand-written parameterized SQL, pydantic v2); schema.sql
  amber/api/       routers: auth, me, documents, collections, search, chat, drive, admin
  amber/util/      config, security (session, RBAC, CSRF), db (psycopg2 pool), audit
  amber/repository.py  all SQL (parameterized)
  amber/rag/       LangChain pipeline: splitter, AclHybridRetriever, reranker, LCEL chains, trace callback
    providers/       llm.py: LangChain model factories (ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings) chosen by settings
  amber/ingest/    parsers, drive sync, worker entrypoint
infra/scripts/          idempotent gcloud scripts: APIs, SAs/IAM, secrets/KMS, GCS, Tasks/Scheduler, LB + Cloud Armor, deploy (never create or delete the existing Firebase/Postgres)
docker-compose.yml      api, worker, web, fake-gcs, Cloud SQL Auth Proxy → cloud amber_dev; auth uses the dev Firebase project
```

## Phase 1: UI (built first, against mocks)
✅ built. `app/ui` uses Next.js 16 with shadcn/ui, dark theme only. There is no mock API layer: pages show empty states until their API exists, and unbuilt actions show a "demo only" toast. `proxy.ts` (Next.js 16's name for middleware) handles route guards, redirecting to /login when there is no session cookie. Admin routes are hidden in the UI and also enforced server-side. UI types live in `lib/types.ts`.

Pages (`app/ui/app/`):
- **`/login`**: Amber branding and a "Continue with Google" button. A consent explainer lists the requested Drive scope and why it's needed: reading files you pick and **saving your uploads to your Drive**.
- **`/search`**: A mode toggle (Quick | Chat) and a filter bar (Sources, Collections/tags, File type, Date range).
  - *Quick*: an answer card with inline `[1]` citations, a ranked source list below, feedback (👍/👎 + comment), and copy.
  - *Chat*: a conversation list on the left (in a drawer on mobile), streamed replies over SSE, citations, and feedback per message.
  - *Source preview panel* (right sheet): the chunk text with the cited span highlighted, doc metadata, page number, and an "Open in Drive" or "Download" link.
  - *Trace panel* (collapsible, under each answer): rewritten query, retrieved chunks with scores and cited/not-cited badges, "N results hidden: no access", model, and latency.
- **`/upload`**:
  - Two tabs, "From computer" (dropzone; PDF/DOCX/PPTX/XLSX/TXT/MD; 50 MB limit) and "From Google Drive" (Google Picker).
  - The "From computer" tab shows a notice: *"Files are saved to your Google Drive in **Amber Uploads**."* If Drive isn't connected (or the token was revoked), the dropzone is disabled and shows a "Reconnect Google Drive" button.
  - A sharing selector (Private / Specific people (email chips) / Everyone at @mydomain) and a collection and tags picker.
    - The helper text says the sharing is also applied to the file in Google Drive.
    - "Everyone at @mydomain" is hidden for consumer (`@gmail.com`) accounts.
  - A live ingestion status table (queued → **saving to Drive** → parsing → embedding → ready / failed + retry). Each row has an "Open in Drive" link once the Drive save finishes.
- **`/profile`**:
  - Account card (Google name/email/avatar, role, sign out, "sign out all sessions").
  - Drive connection card (status, granted scopes, last sync, a link to the `Amber Uploads` folder, reconnect/disconnect).
  - My documents (edit sharing/tags, delete). Delete removes the doc from Amber's index; an opt-in checkbox also moves the Drive file to Drive trash.
  - My chat and search history (view, delete one, delete all).
- **`/admin`** (tabs):
  - **Documents**: table with status/source/owner, view ACL, re-index, delete.
  - **Users**: list, promote/demote, deactivate.
  - **Audit logs**: filterable by user, action, and doc; CSV export.
  - **Query traces**: full trace view per query.
  - **Analytics**: queries/day, active users, feedback ratio, ingestion failures.
  - **Settings**: model, chunk size/overlap, top-k, Drive sync interval, upload limits.

UI security from day one:
- Render answers through `react-markdown` without raw HTML (`rehype-sanitize`), because LLM output and doc text are untrusted.
- Never use `dangerouslySetInnerHTML`.
- Use a strict CSP with nonces via middleware, plus HSTS, `X-Frame-Options: DENY`, `Referrer-Policy`, and `Permissions-Policy` in `next.config`.
- Store no tokens in `localStorage`.

## Phase 2: Auth (existing cloud Firebase + Google, one consent screen) ✅ built
- **Server-side redirect flow** (changed from the original Google popup + Firebase JS SDK design: the popup can't do PKCE, and this way no token reaches browser JavaScript):
  - "Continue with Google" is a plain link to `GET /api/auth/google/start`. The API redirects to Google with `openid email profile` + `https://www.googleapis.com/auth/drive.file`, `access_type=offline`, PKCE (S256), `state` and `nonce`. The state, nonce and verifier sit in an encrypted, 10-minute, single-use `SameSite=Lax` cookie. Sign-in and the Drive permission happen on one screen.
  - `GET /api/auth/google/callback`:
    1. Checks the state, exchanges the code server-side, and verifies the ID token (signature, aud, iss, exp, nonce, `email_verified`).
    2. Encrypts the **refresh token** with envelope encryption (Cloud KMS key, AES-256-GCM, bound to the user id) and stores it in `oauth_tokens`. If Google omits the refresh token for a returning user with none on file, the flow repeats once with `prompt=consent`.
    3. Signs in to Firebase **server-side** (`signInWithIdp`), calls `create_session_cookie`, and sets the session cookie: **HttpOnly, Secure, SameSite=Strict**, 5 days, `__Host-` prefix over https. It then lands on the app with a same-origin meta refresh, so the browser sends the Strict cookie straight away.
- Web and API share one origin through the GCP HTTPS Load Balancer (`/api/*` → FastAPI); locally a Next.js rewrite does the same. There is no CORS surface. CSRF is blocked by SameSite=Strict, an Origin check, and a required `X-Amber-CSRF` double-submit header on mutating requests.
- The `current_user` dependency verifies the session cookie's signature and expiry on every request. It then checks revocation: "sign out everywhere" uses Firebase's revoke-all, with that timestamp cached per instance for 60 s. A single-device sign-out is recorded in the `revoked_sessions` table as the cookie's SHA-256 hash, so a copied cookie stops working immediately. The dependency then loads the user from the DB. Roles are **authoritative in Postgres**, not client claims. Deactivated users are rejected. The web app gates pages server-side with `requireUser()` → `/api/me`.
- Also built: sign out, sign out of all devices (`revoke_refresh_tokens`), Drive disconnect (revokes at Google, deletes the token), Drive reconnect (`prompt=consent`), and audit rows for each of these. `schema.sql` documents `users`, `oauth_tokens` and `audit_log` (created manually).
- Also: per-IP rate limits on the auth endpoints (in-memory per instance; Cloud Armor adds a global limit in Phase 7). The audit IP comes from `X-Forwarded-For` only when the request arrives through a configured trusted proxy (`AMBER_TRUSTED_PROXIES`). A bootstrap admin email only grants admin when the account is first created. Drive disconnect reports whether Google confirmed the revocation.
- Scope rationale: `drive.file` covers only files picked through the Picker **and files/folders Amber itself creates**, so desktop uploads into the user's Drive need no extra scope. It avoids Google's restricted-scope CASA audit and is least privilege. Broader whole-Drive indexing can come later under `drive.readonly`, after verification.

## Phase 3: Backend and data model (existing Postgres + pgvector)
No ORM and no migration framework. Tables are **created manually** in Postgres by the project owner; the app, CI and deploy scripts never create or alter them. **`app/api/schema.sql`** is the reference definition of what the code expects; Phase 3 adds the pgvector extension, new tables, grants and RLS policies to it. All queries are hand-written, parameterized psycopg2 SQL in `amber/repository.py`.

Tables:

| Table | Columns / notes |
|---|---|
| `users` | id, firebase_uid, email, domain(`hd`), name, avatar, role, status, `drive_uploads_folder_id`, timestamps |
| `oauth_tokens` | user_id, encrypted_refresh_token, kms_key_version, scopes |
| `documents` | id, owner_id, source(always `drive`), origin(`desktop_upload`/`drive_picker`), drive_file_id (unique per owner), title, mime, staging_gcs_uri (nullable, desktop uploads only), sha256, status, error, collection_id, timestamps |
| `document_access` | document_id, principal_type(user/domain), principal_value, origin(manual/drive_sync). **This is the ACL** |
| `chunks` | id, document_id, ord, text, page, `embedding vector(1536)` HNSW cosine, `tsv tsvector` GIN |
| `collections`, `tags`, `document_tags` | |
| `conversations`, `messages` | messages hold trace_id |
| `query_traces` | query, rewritten query, filters, retrieved chunk ids+scores, cited ids, hidden_count, model, tokens, latency |
| `feedback` | |
| `audit_log` | Append-only. The app DB role has INSERT only; no UPDATE/DELETE |
| `settings` | |

**ACL enforcement (core security invariant):**
- Every retrieval SQL joins `chunks → documents → document_access`. It matches on the principal set `{user:<email>, domain:<hd>}` **inside the same query as the vector search**, as a pre-filter rather than a post-filter.
- Postgres **Row-Level Security** on `documents`/`chunks` uses `SET LOCAL app.user_email/app.user_domain` per transaction as defense in depth.
- `hidden_count` comes from a separate count-only query, so no content from hidden docs is ever read.

**API rules:**
- Pydantic validation on all inputs.
- Object-level authz on every `/documents/{id}`, enforced by the same ACL (protects against IDOR).
- `require_admin` dependency on `/admin/*`.
- Rate limiting with `slowapi`, keyed per user, stricter on search, chat, and upload.
- Every access, search, share change, and admin action is written to `audit_log`.

## Phase 4: Ingestion pipeline
- **Desktop upload → user's Google Drive → index:**
  1. **API (synchronous):**
     - Require a valid Drive connection, or return `409 DRIVE_NOT_CONNECTED` so the UI shows "Reconnect".
     - Check type by magic bytes rather than extension, enforce the size cap, and compute the sha256. If this user already has the same sha256, offer the existing doc instead of re-uploading.
     - Stream the file to the **private GCS staging bucket** (CMEK, uniform access, public-access prevention). Insert a `documents` row (`origin=desktop_upload`, status `queued`) and enqueue a Cloud Tasks job.
  2. **Worker: save to Drive.**
     - Find or create the user's `Amber Uploads` folder (`files.create` with folder mime type; the id is cached in `users.drive_uploads_folder_id` and recreated if trashed or deleted).
     - Upload with a **resumable** `files.create` into that folder, as the original format (no conversion to Google Docs, to preserve fidelity).
     - Tag the file with `appProperties.amberDocumentId`. **Retries are idempotent:** before creating, the worker searches for an existing file with that appProperty, so a retried task never makes duplicates.
     - Save `drive_file_id` and set status `saving_to_drive` → `parsing`.
  3. **Worker: apply sharing in Drive** (Drive is the single source of truth for access):
     - "Specific people" becomes `permissions.create` (type=user, role=reader, `sendNotificationEmail=false`).
     - "Everyone at @mydomain" becomes type=domain, role=reader.
     - "Private" adds no permissions.
     - `document_access` is then filled **from `permissions.list`**, the same mapping as Picker files, so Amber's ACL and Drive's sharing can't drift apart. Changing sharing later in Amber calls the same Drive permissions APIs first and then re-syncs. Every share change is audited.
  4. **Worker: index.** Parse from the staged GCS copy, then chunk and embed (below). The **staging object is deleted** once indexing succeeds, and a bucket lifecycle rule deletes anything older than 3 days. Drive holds the only lasting copy of the file.
  - **Failure handling:**
    - Drive save fails (`storageQuotaExceeded`, `insufficientPermissions`, token revoked): status `failed` with a specific message ("Your Google Drive is full" / "Reconnect Google Drive"). Retry is available.
    - The file is **not** indexed unless the Drive save succeeded, so every indexed doc always exists in Drive.
    - Drive API errors are retried with exponential backoff on 429/5xx.
- **Afterwards**, desktop-uploaded files behave exactly like Drive files. The Drive `changes` sync (below) picks up edits, renames, sharing changes, and trash/delete in Drive and updates or removes them in Amber.
- **Worker:** a separate Cloud Run service with no public ingress, OIDC-authenticated from Cloud Tasks, and its own least-privilege service account.
  - Parsers are an attack surface, so they run sandboxed with timeouts and memory limits.
  - Parsing uses `pypdf`/`unstructured` and Docling for PDF/Office files.
  - The worker decrypts the user's refresh token with KMS (`roles/cloudkms.cryptoKeyDecrypter` on the token key only) for both Drive saves and Drive reads. Access tokens are held in memory only and never logged.
  - Chunking uses LangChain's `RecursiveCharacterTextSplitter.from_tiktoken_encoder` (~800 tokens, 15% overlap) and keeps page and heading metadata on each `Document`.
  - Embeddings come from `GoogleGenerativeAIEmbeddings` (`task_type=RETRIEVAL_DOCUMENT`, `output_dimensionality=1536`), in batches with retry/backoff, written into Amber's own `chunks` table. Status updates are pushed back to the UI by polling or SSE.
  - LangChain document loaders that fetch URLs are not used; Amber's own parsers produce the `Document`s.
- **Drive:**
  - The Picker returns file ids. The backend fetches content with the user's decrypted refresh token; Google Docs/Sheets/Slides are exported to text.
  - It calls `permissions.list` and maps the result to `document_access`:
    - user/email entries become `user` principals.
    - `domain` entries become `domain` principals.
    - `anyone`/`group` entries are **conservatively ignored**, so only the explicit principals plus the owner get access. Group expansion needs the Admin SDK and is out of scope for v1.
  - Cloud Scheduler triggers a periodic re-sync via the Drive `changes` API (per-user page tokens), which updates content and ACLs. Revoked access removes the ACL rows immediately.

## Phase 5: RAG and traceability
The pipeline in `amber/rag/` is built as a **LangChain LCEL chain**:
1. **Query rewrite:** a history-aware rewrite chain (`ChatPromptTemplate | ChatGoogleGenerativeAI | StrOutputParser`) that uses chat history in Chat mode and passes the query through unchanged in Quick mode.
2. **Retrieval with a custom `AclHybridRetriever(BaseRetriever)`:**
   - It's built **per request** with the authenticated user's principals. It runs Amber's own SQL: pgvector cosine plus Postgres FTS, fused with RRF and ACL-filtered in the same query (with RLS session vars set), top 40.
   - It returns `Document`s with `chunk_id`, `document_id`, page, and vector/keyword/RRF scores in metadata.
   - **LangChain's `PGVector` store is deliberately not used.** Its own schema and JSONB metadata filters would bypass the `document_access` join and RLS, which are the core security invariant.
3. **Rerank:** a `ContextualCompressionRetriever` with `CrossEncoderReranker` (a local `BAAI/bge-reranker-base` cross-encoder in the API container, so document text isn't sent to another service just to rerank). It keeps the top 8. Gemini-based `LLMListwiseRerank` can be switched on in Admin › Settings.
4. **Generate:** a prompt containing numbered context blocks, then `ChatGoogleGenerativeAI` (streaming). The answer streams to the UI over SSE using `astream_events`. Citations come back as structured output (`with_structured_output` / `[n]` markers) bound to chunk ids.
5. **Trace:** a custom `AsyncCallbackHandler` (`AmberTraceHandler`) records each step (rewritten query, retrieved and reranked docs with scores, prompt token counts, model, latency, cited ids) and saves it to `query_traces`.
   - **LangSmith tracing is disabled** (`LANGCHAIN_TRACING_V2=false`, enforced in config) so document content never goes to a third-party tracing service.

LangChain usage rules (security):
- Pin `langchain-core`, `langchain`, `langchain-google-genai`, and `langchain-community` to exact versions, and check them with `pip-audit`.
- No agents, tools, `langchain_experimental`, `PythonREPL`, or SQL agents.
- Never pass `allow_dangerous_deserialization=True`, and don't load serialized chains from disk or user input.

Prompt-injection posture: retrieved text is wrapped in delimited "untrusted context" blocks, and the system prompt says to answer only from context and to ignore instructions inside documents. The chain has no tool or function calling, so a malicious document can't cause actions. Citations are validated server-side against the retrieved set.

Gemini API access:
- The API key lives in Secret Manager (`gemini-api-key`) and is mounted only into the api and worker services.
- The key is restricted to the Generative Language API, and requests use `max_retries`/timeouts.
- The project must be on the **paid tier**, because free-tier data may be used to improve Google's products.
- Trade-off vs Vertex: no regional data-residency pinning and key-based rather than IAM auth. Revisit if residency becomes a requirement; it's a one-line switch in `amber/rag/providers/llm.py` to `langchain-google-vertexai`.

## Phase 6: Admin, analytics, settings
- Wire the admin tabs to `/admin/*`.
- Analytics are SQL aggregates over `query_traces`, `feedback`, and `documents`.
- Settings are versioned rows, and each change is audited.
- Admins can never read another user's **private document content** through the admin UI. They can see metadata, ACLs, and traces (trace chunk text is redacted unless the admin already has access). This keeps "admin" from becoming a data-exfiltration path. *(Flag: confirm this policy.)*

## Phase 7: Hardening and deploy (GCP)
- **Scripted `gcloud` deploy (no Terraform for now).**
  - Bash scripts live in `infra/scripts/`, each **idempotent** (it checks with `describe` before `create`, so re-running it is safe) and run with `set -euo pipefail`.
  - All settings come from a single `infra/scripts/env/<dev|staging|prod>.env` file (project ids, region, existing SQL instance connection name, Firebase project id). The file holds no secrets and is committed.
  - Scripts:
    - `01-enable-apis.sh`: Run, Artifact Registry, Cloud Build, SQL Admin, Secret Manager, KMS, Tasks, Scheduler, Generative Language (Gemini) API, Drive, Compute.
    - `02-service-accounts.sh`: one SA each for `amber-web`, `amber-api`, `amber-worker`, and `amber-deployer`. Least-privilege role bindings, including `roles/cloudsql.client` + `roles/cloudsql.instanceUser` on the existing instance, and `gcloud sql users create --type=cloud_iam_service_account` for the api/worker SAs.
    - `03-secrets-kms.sh`: a KMS keyring and key (token encryption and bucket CMEK) and empty Secret Manager secrets (`oauth-client-secret`, `gemini-api-key`). Secret *values* are added by hand with `gcloud secrets versions add`, and never live in the repo or scripts.
    - `04-storage.sh`: a private GCS **staging** bucket (uniform access, public-access prevention enforced, CMEK, lifecycle delete after 3 days). Drive is the lasting store for uploads.
    - `05-queues.sh`: the Cloud Tasks queue and Cloud Scheduler jobs (Drive re-sync). Both are OIDC-authenticated to the worker.
    - `06-edge.sh`: a global HTTPS LB with a managed cert, serverless NEGs (`/api/*` → api, `/*` → web), and a **Cloud Armor** policy (OWASP preconfigured rules + rate limiting). Cloud Run ingress is set to `internal-and-cloud-load-balancing`; the worker is internal only.
    - `deploy.sh <env>`: builds images with Cloud Build into Artifact Registry, then `gcloud run deploy` for api/worker/web. Images are pinned by digest, secrets mounted with `--set-secrets`, each service runs as its own SA, and private VPC egress is used to reach the existing Postgres.
  - **Guardrail:** the scripts only *reference* the existing Firebase project and Postgres instance. They contain no `gcloud sql instances create/delete/patch` or Firebase project mutations, and CI greps for these and fails if any appear. If the instance still has a public IP, restrict authorized networks to none (a one-time manual step, documented) and rely on the connector/private IP.
  - **Terraform is optional later.** Because each script maps to one resource group, it can be converted to Terraform with `terraform import` without recreating anything.
- **CI (GitHub Actions):** lint/typecheck, pytest, Playwright, plus `pip-audit`, `npm audit`, Semgrep, gitleaks, Trivy container scans, and Dependabot.
- **CD:** GitHub Actions runs `infra/scripts/deploy.sh` as `amber-deployer` through **Workload Identity Federation** (no JSON keys), with prod deploys gated by a GitHub environment approval. The one-time setup scripts (01–06) are run by hand by an admin.
- **Retention:** user "delete my history" hard-deletes the user's data. Account deletion revokes the Google token and purges the user's docs and chunks.

## Verification
- **Phase 1:** `pnpm dev` in `app/ui`. Use Playwright to click through every page in both modes, check that admin routes redirect for members, and check that a markdown-XSS payload in a mock answer renders inert.
- **Infra smoke check (before step 3):** connect through the Cloud SQL connector as `amber_app` to `amber_dev`, run `SELECT extversion FROM pg_extension WHERE extname='vector'`, and confirm `amber_app` can't `UPDATE audit_log`. Sign in with Google against the dev Firebase project and verify the ID token in FastAPI.
- **Local full stack:** `docker compose up` (api, worker, web, fake-gcs, Cloud SQL Auth Proxy → cloud `amber_dev`, dev Firebase project).
- **pytest:** unit tests only. They never connect to a database or call external services, so they can't affect data whenever they run. Database-backed and timing-dependent tests were deliberately removed; verify DB behaviour manually against a dev database. Firebase token verification is mocked in unit tests and hits the dev Firebase project in integration tests.
  - Auth: no cookie, revoked cookie, deactivated user, member hitting `/admin`.
  - CSRF: missing header is rejected.
  - **ACL tests:** user A uploads a private doc and user B's search must not return it; hidden_count increments; IDOR on `/documents/{id}` returns 404; RLS blocks a direct query without the session vars.
  - Drive ACL mapping: unit tests with fixture `permissions.list` payloads.
  - **Desktop upload → Drive** (Drive client mocked in unit tests, and a dev Google account in integration tests):
    - The file lands in `Amber Uploads` with the `amberDocumentId` appProperty.
    - Retrying the task creates no duplicate.
    - "Specific people" sharing creates matching Drive permissions, and `document_access` matches `permissions.list`.
    - A quota-exceeded or revoked-token error sets status `failed` and indexes nothing.
    - Uploading with Drive disconnected returns 409.
    - The staging object is deleted after indexing.
    - Trashing the file in Drive removes it from search after the next sync.
  - RAG: chain unit tests use LangChain fakes (`FakeListChatModel`, `DeterministicFakeEmbedding`), so they need no API calls. `AclHybridRetriever` is tested directly: user B must get zero docs from user A's private doc, even with an identical query. A golden set of Q&A over fixture docs (run against the real Gemini API in a nightly job) checks citation validity and that `AmberTraceHandler` saved the trace. A config test asserts LangSmith tracing is off.
- **Deploy scripts:** run each setup script twice against dev (the second run must be a no-op), run `deploy.sh dev`, then confirm the Cloud Run URLs aren't directly reachable (only through the LB) and the worker rejects unauthenticated requests.
- **Security pass:** run `/security-review`, plus OWASP ZAP baseline against the staging URL.

## Build order
1. Scaffold the monorepo.
2. **UI with mocks (all pages)**.
3. Configure the existing Firebase and Postgres (see the prerequisites above), then build the auth flow.
4. Core API (tables created manually on the existing Postgres).
5. Drive client (token refresh, `Amber Uploads` folder, resumable upload, permissions) and the desktop upload → Drive → index pipeline.
6. Search and chat with traces.
7. Drive Picker and `changes` sync (shared with desktop uploads).
8. Admin, analytics, and settings.
9. gcloud setup scripts, `deploy.sh`, CI/CD, and the hardening pass (Terraform optional later).
