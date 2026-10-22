# Deploying Amber to Google Cloud

**Status: deployed.** Amber runs on Cloud Run at [amber.kathalyst.ai](https://amber.kathalyst.ai), built and deployed with `deploy/cloudrun.sh` (`setup`, `secrets`, `deploy`). This file keeps the reasoning behind the setup and a checklist for a fresh deployment. Sections 4, 6 and 12 say what has been done and what is still open. Commands in §9 are for reference and for the steps the script doesn't cover (Cloud Scheduler).

## 0. Your answers and what they mean

| Your answer | Consequence for the plan |
|---|---|
| External app, used by companies on Google Workspace | Google's rules for restricted scopes apply (§6). This is the biggest risk to the plan. |
| Existing Cloud SQL instance, India region | Deploy Cloud Run in the **same region** (`asia-south1` Mumbai or `asia-south2` Delhi, whichever the instance is in). Cloud SQL has no free tier, so the instance you already pay for is your main fixed cost. |
| Custom domain (`amber.kathalyst.ai`) | The script takes it as `PUBLIC_BASE_URL`; without it the app uses the `*.run.app` URL. Cloud Run is still reached directly (no load balancer), so Option A below stays deferred. |
| Up to 200 MB uploads, later | **Decided: 30 MB for now** (§3). 200 MB is a future redesign. |
| Free tier, hobby project | No load balancer, no Cloud Armor, no minimum instances, no VPC connector (§7). `deploy/cloudrun.env.example` defaults `REGION` to `asia-southeast1`; set it to the Cloud SQL instance's region. |

**Decision: Option B** (two Cloud Run services, the web app proxies `/api` to the API). Options A and C are kept in §2 for when things change.

---

**Decisions made**

1. **Drive access:** narrow `drive.file` scope plus the Google Picker (§6). No Google verification needed. (A short-lived folder-import feature requested `drive.readonly`; it has been removed.)
2. **Upload limit:** 30 MB for now.
3. **Gemini key:** from a billing-enabled project, so customer documents are not on the free tier.
4. **Database:** the existing Cloud SQL database you have already deployed, not a new one (§5).

---

## 1. Overview

| Piece | What it is |
|---|---|
| `api` | FastAPI (Python 3.12), Postgres + pgvector, Firebase Admin, Drive, Gemini |
| `ui` | Next.js 16 (pnpm). Serves pages and proxies `/api/*` to the API |

The browser must see the web app and `/api/*` on **one origin**. The code depends on it: `__Host-` cookies (`security.py`), a JavaScript-readable CSRF cookie, and an OAuth redirect built from `AMBER_PUBLIC_BASE_URL`. In Option B the browser only talks to `amber-web`, which forwards `/api/*` to `amber-api`, so this holds.

The repo has `api/Dockerfile`, `ui/Dockerfile`, `ui/cloudbuild.yaml` and `deploy/cloudrun.sh` (§12). There is no CI/CD yet.

---

## 2. Hosting options

### Option B (chosen): Cloud Run ×2, web proxies the API

```
Browser ──▶ https://amber-web-<project-number>.<region>.run.app   (amber-web)
                └─ Next.js rewrite  /api/*  ─▶  amber-api (Cloud Run)
                                                    └─ Cloud SQL (existing instance, India)
```

- `next.config.ts` already rewrites `/api/*` to `AMBER_API_ORIGIN`.
- The web URL is predictable before the first deploy (`SERVICE-PROJECTNUMBER.REGION.run.app`), so the Google OAuth redirect URI can be registered first.
- API ingress is `all` with Amber's own cookie auth, instead of `internal`. `internal` would need the web service to use VPC egress. That is possible (Direct VPC egress has no hourly charge) but adds setup for little gain on a hobby project. Browsers can't send the API the web origin's `__Host-` cookies directly, so the API's own URL is not a bypass.
- No Cloud Armor, so abuse protection is only the in-app per-instance rate limiter. Acceptable for a hobby project.

### Option A (later, production): load balancer + Cloud Run
Global HTTPS load balancer with path routing (`/api/*` → api, rest → web), Cloud Armor, services on `internal-and-cloud-load-balancing`. Needs a **custom domain** (managed cert) and costs about $18+/month fixed. Move to it when you have a domain and paying customers. Only the front door changes; images, secrets and database stay the same.

### Option C: Firebase Hosting in front of Cloud Run (not recommended)
Firebase Hosting removes all cookies from requests to Cloud Run except one named `__session`. Amber needs three (session, CSRF, OAuth state), so this means redesigning the auth cookies. This is from my recollection of the Firebase docs; check the current docs before ruling it out. Firebase App Hosting (managed Next.js) has the same single-origin questions and is untested for this app.

---

## 3. The 200 MB upload requirement (decided: 30 MB for now)

A 200 MB upload cannot work through Option B for three separate reasons:

1. **Cloud Run caps HTTP/1 request bodies at 32 MiB.** Lifting it needs HTTP/2 end to end, and `next start` doesn't speak HTTP/2 cleartext.
2. **Next.js's proxy buffers request bodies** (`proxyClientMaxBodySize`, default 10 MB), so the `/api` rewrite would need that raised too.
3. **Memory and time.** Indexing happens inside the upload request. Parsing 200 MB of PDF or Office content needs several GiB of memory, which eats the free tier (§7) quickly and risks timeouts.

**Decision: 30 MB.** Today the Admin › Settings default is 50 MB and the form accepts up to 200 MB (`LIMITS` in `api/amber/ingest/settings.py`); only the proxy limit was set (`proxyClientMaxBodySize: "32mb"` in `ui/next.config.ts`). So after deploy, set the max file size to 30 in Admin › Settings. A larger value is accepted by the form but fails at the Cloud Run or proxy limit. Lowering `LIMITS` to match is still open (§12).

**If you truly need 200 MB later**, it's a feature, not a config change: the browser uploads straight to a Cloud Storage bucket with a signed resumable URL, and the API then reads from the bucket and indexes in the background (Cloud Tasks), with 4–8 GiB of memory for the worker. The bucket is free only in `us-*` regions (5 GB), so in India it costs a few cents a month. Say if you want this designed.

---

## 4. Things in the code to fix before the first deploy

1. **Dockerfiles and `.dockerignore` files.** Done (`api/`, `ui/`).
2. **`output: "standalone"`** and `experimental.proxyClientMaxBodySize`. Done (`ui/next.config.ts`, 32 MB).
3. **API start command.** The image runs `python main.py` with `AMBER_HOST=0.0.0.0` and `AMBER_PORT=8000`, and the deploy passes `--port 8000`. Done. (This replaced the `uvicorn ... --factory` command first planned.)
4. **tiktoken downloads its vocabulary at runtime** (`cl100k_base`). **Still open:** download it during the image build and set `TIKTOKEN_CACHE_DIR`, or the first upload on each cold instance is slow or fails.
5. **Database connections.** Each request opens its own connection (`db.py`), and sign-in checks open two. Small Cloud SQL tiers allow only a few dozen connections, so the deploy caps the API at `--max-instances 3` and `--concurrency 10`. Done. The agent's Postgres pool adds up to 20 connections per instance (`main.py`), so keep the Cloud SQL connection limit in mind when raising either number.
6. **Per-instance rate limits** only. Fine for now.
7. **Search and chat are built** (Quick and Chat modes, the agent, collections, traces and Opal voice), so this deploy covers the whole app.

---

## 5. Database (the Cloud SQL database you already deployed)

You chose to use the existing database rather than create a new one. Everything here is additive: no creating, patching or deleting the instance or database.

1. **Check first (read-only):** the instance's region and Postgres version, whether it has a **public IP**, and whether `pgvector` is already installed. If it is private-IP only, Cloud Run needs Direct VPC egress into that network (extra setup, no hourly cost).
2. **This database probably holds dev data.** `PLAN.md` and `.env.example` describe it as the dev database (`amber_dev`). Using it for the deployed app means the deployed app and your local dev setup share users, documents, tokens and settings. Consequences to accept:
   - Local testing can change what deployed users see. Stop running local dev against it once real users arrive, or give local dev its own database later.
   - Existing rows (including any users with the old full-`drive` token) will be present. Run a one-off check for test data you don't want to keep.
3. **Take an on-demand backup before the first deploy**, and confirm automated backups and point-in-time recovery are on.
4. **Schema:** re-apply `api/schema.sql` as the schema owner (`amber_migrator`) through the Cloud SQL Auth Proxy from your machine: `psql "$AMBER_MIGRATOR_DSN" -v ON_ERROR_STOP=1 -f api/schema.sql`. It is idempotent. It adds `settings.updated_by` and `DELETE` on `users`, which the admin page needs. Skip `CREATE EXTENSION vector` if it already exists.
5. **Connect from Cloud Run** with the built-in Cloud SQL connection (`--add-cloudsql-instances PROJECT:REGION:INSTANCE`). It exposes a Unix socket, needs no VPC, and works with a public-IP instance. Use the existing `amber_app` role with a password stored in Secret Manager. The secret `AMBER_DATABASE_DSN` looks like `postgresql://amber_app:<password>@/<existing db name>?host=/cloudsql/PROJECT:REGION:INSTANCE`. (The config comments describe an Auth Proxy sidecar with IAM login instead. That avoids a database password but needs a multi-container service, so skip it for now.)
6. **Row-level security.** `schema.sql` now enables **and forces** RLS on `documents`, `chunks` and `document_access` and defines their policies, so the policies also bind the table owner. Superusers and `BYPASSRLS` roles still skip them, so connect as `amber_app`, never as a superuser. The search query also checks `document_access` explicitly. See `DECISION.MD` §2 and §14.

---

## 6. Google sign-in and Drive access (`drive.file` + Picker)

**Why:** the original full `drive` scope is restricted. For an External app that means a 100-user cap, an "unverified app" warning, 7-day refresh tokens in Testing mode, and verification that needs a domain you own and a paid annual security review. `drive.file` is not restricted, so none of that applies. Sign-in requests only `openid`, `email`, `profile` and `drive.file` (`api/amber/util/google_oauth.py`). `drive.readonly` is **not** requested.

**What `drive.file` allows:** Amber can see only files it created (everything uploaded to `Amber Uploads`) and files the user explicitly picks in the Google Picker. It can change sharing on those files. It can't browse the user's whole Drive, and it can't list the files inside a folder. So users browse into folders in the Picker and multi-select files; selecting a whole folder is turned off.

**Consent screen:** scopes `openid`, `email`, `profile` and `drive.file` only. Set publishing status to **In production**, because Testing mode expires tokens after 7 days. No sensitive or restricted scopes means no verification is required, but check the console, since Google may still ask for basic branding details. The Search Console ownership tag in `ui/app/layout.tsx` is for domain verification, not a scope.

**Users who signed in earlier.** Anyone who connected while `drive.readonly` or the old full `drive` scope was requested still holds that grant until they reconnect. The code ignores it: Picker tokens and the agent are always narrowed to `drive.file`.

**Code changes this needed. Status: done.**
1. `api/amber/models.py`: `DRIVE_SCOPE` is `drive.file`, and `can_manage_drive_sharing` accepts it. Users whose stored token has an older scope are sent through consent again at their next sign-in.
2. **Picker token endpoint:** `POST /api/drive/picker-token` returns a short-lived access token (about one hour) minted from the stored refresh token and narrowed to `drive.file`. The refresh token never reaches the browser. The Picker needs a browser API key restricted to the web origin and the Picker API (`AMBER_PICKER_API_KEY`) and the Cloud project number as the app ID (`AMBER_GOOGLE_CLOUD_PROJECT_NUMBER`, which the script fills in).
3. **UI:** `drive-picker-panel.tsx` uses Google's Picker. Picked file IDs go to `/api/drive/import` in batches of 5.
4. **Removed** the Drive browsing endpoint (`GET /api/drive/files`). `POST /api/drive/folder-files` remains but always returns 409, as dead code left from the removed folder import.
5. **CSP:** `ui/proxy.ts` allows the Picker's script, frames and thumbnails (`apis.google.com`, `docs.google.com`, `drive.google.com`, `content.googleapis.com`, `accounts.google.com`, `*.googleusercontent.com`). Test any change in the browser.
6. **Behavior to expect:**
   - Files imported earlier under the full scope may stop allowing sharing changes until the user re-picks them. The existing Drive error message says so.
   - Importing a file the user can only view (not own) may fail when reading its permission list. The importer reports per-file failures.
   - Google Docs, Sheets and Slides still export to Office formats once picked.
   - Drive permission sync (the Changes API watch) works under `drive.file`, and it needs a public HTTPS `AMBER_PUBLIC_BASE_URL`.

**Other settings**
1. Add `https://amber-web-<project-number>.<region>.run.app/api/auth/google/callback` as an authorized redirect URI on the Firebase-created web client.
2. Add the `run.app` hostname under Firebase Console › Authentication › Settings › Authorized domains.
3. Set `AMBER_BOOTSTRAP_ADMIN_EMAILS` to your email (only applies when that account is first created).
4. **Gemini key (decided):** create the key in a project with billing enabled, so requests are on the paid tier rather than the free tier, which may use submitted content to improve Google's products. Keep it in Secret Manager. Embedding costs are small, but set a budget alert (§7).
5. **Company admins:** Workspace admins can still restrict third-party apps. If a company blocks sign-in, its admin must allow the OAuth client ID. Put this in your onboarding note.

---

## 7. Free-tier fit

Always check Google's current pricing pages. Limits below are from memory.

| Service | Free allowance (approx.) | Amber's use | Verdict |
|---|---|---|---|
| Cloud Run | 2M requests, 180k vCPU-seconds, 360k GiB-seconds per month | Scale to zero, request-based billing | Fits for light use. **Use `--min-instances 0`** (idle instances are billed) |
| Cloud Build | ~120 build-min/day | A few builds per week | Fits |
| Artifact Registry | 0.5 GB | Two images, likely over 0.5 GB | Cents per month; delete old tags |
| Secret Manager | 6 active versions | 8 secrets | Slightly over; keep one version each. Cents per month |
| Firebase Auth (Google sign-in) | Free | Sign-in | Fits |
| Cloud Logging | 50 GiB/month | Low | Fits |
| Cloud KMS | None, ~$0.06 per key version/month | Token encryption key (**required in prod**) | A few cents |
| Cloud SQL | **None** | Existing instance | Already paid; a new database on it adds only storage |
| Load balancer, Cloud Armor | None | Not used in Option B | Skipped |
| Outbound traffic | Small free amount | Pages and uploads | Pennies at hobby volume |
| Gemini API | Not used (billed key, decided) | Embeddings, chat and Opal voice | Per-token cost; voice sessions cost the most. Covered by the budget alert |
| PostHog | Outside Google Cloud | Optional analytics and logs | Check PostHog's own free tier |

Expect a bill of well under $5/month beyond Cloud SQL if used lightly. **Set a billing budget with email alerts at $5 and $10 before deploying anything.**

Cold starts: with scale-to-zero the first request after idle takes several seconds (Python and LangChain imports). Fine for a hobby tool.

---

## 8. One-time project setup

```bash
export PROJECT_ID=<gcp-project>      # same project as Firebase
export REGION=<instance region>      # asia-south1 or asia-south2
gcloud config set project $PROJECT_ID
```

1. **Billing budget and alerts** (§7).
2. **Enable APIs:** `deploy/cloudrun.sh setup` enables Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud KMS, Cloud SQL Admin, Drive, Generative Language and Identity Toolkit. Enable by hand: **Google Docs, Google Sheets, Google Picker** (the agent and the Picker need them) and **Cloud Scheduler**. Create the restricted Picker browser API key.
3. **Artifact Registry:** one Docker repository `amber` in `$REGION` (the script creates it).
4. **Service accounts:**

   | Account | Roles |
   |---|---|
   | `amber-api` | `cloudsql.client`, `secretmanager.secretAccessor` (only its secrets), `cloudkms.cryptoKeyEncrypterDecrypter` (only the token key), Firebase Auth admin |
   | `amber-web` | None beyond logging |
   | `amber-deployer` (later, for CI) | `run.admin`, `artifactregistry.writer`, `iam.serviceAccountUser` on the two runtime accounts |

   Don't create or download JSON keys. Cloud Run supplies credentials to the attached service account, and `config.py` already uses them when `GOOGLE_APPLICATION_CREDENTIALS` is unset.
5. **KMS:** a key ring and symmetric key; its resource name is `AMBER_TOKEN_KMS_KEY`. Prod refuses to start without it, or if `AMBER_LOCAL_TOKEN_KEY` is set.
6. **Secrets** (create empty, add values by hand, never commit):

   | Secret | Env var |
   |---|---|
   | `amber-oauth-client-secret` | `AMBER_GOOGLE_OAUTH_CLIENT_SECRET` |
   | `amber-firebase-web-api-key` | `AMBER_FIREBASE_WEB_API_KEY` |
   | `amber-gemini-api-key` | `AMBER_GEMINI_API_KEY` (also used by Opal voice) |
   | `amber-state-cookie-key` | `AMBER_STATE_COOKIE_KEY` (a new Fernet key, not the dev one; `secrets` generates it) |
   | `amber-database-dsn` | `AMBER_DATABASE_DSN` |
   | `amber-litellm-api-key` | `AMBER_LITELLM_API_KEY` (add a placeholder value if you don't use LiteLLM; `deploy` refuses to run with an empty secret) |
   | `amber-drive-sync-secret` | `AMBER_DRIVE_SYNC_ADMIN_SECRET` (`secrets` generates it; Cloud Scheduler sends it as `X-Amber-Drive-Sync-Secret`) |
   | `amber-posthog-api-key` | `AMBER_POSTHOG_API_KEY` (PostHog project token; with `AMBER_POSTHOG_HOST` set, backend analytics and log export turn on) |

   Plain env vars: `AMBER_ENV=prod`, `AMBER_PUBLIC_BASE_URL=https://amber-web-<project-number>.<region>.run.app`, `AMBER_COOKIE_SECURE=true`, `AMBER_GOOGLE_OAUTH_CLIENT_ID`, `AMBER_FIREBASE_PROJECT_ID`, `AMBER_TOKEN_KMS_KEY`, `AMBER_BOOTSTRAP_ADMIN_EMAILS`, `AMBER_PICKER_API_KEY`, `AMBER_GOOGLE_CLOUD_PROJECT_NUMBER`, `AMBER_AGENT_MODEL_NAME`, `AMBER_LITELLM_BASE_URL`, `AMBER_GEMINI_LIVE_MODEL`, `AMBER_GEMINI_LIVE_MAX_SESSION_SECONDS` and `AMBER_POSTHOG_HOST`. The script writes all of these from `deploy/cloudrun.env`. Leave `AMBER_TRUSTED_PROXIES` empty at first (audit-log IPs will show the proxy, not the user).

---

## 9. Build and deploy

The script does the build and both deploys:

```bash
cp deploy/cloudrun.env.example deploy/cloudrun.env   # fill in; git-ignored
deploy/cloudrun.sh setup      # one time: APIs, registry, service accounts, KMS, empty secrets
deploy/cloudrun.sh secrets    # prompts for each secret value; nothing is echoed or stored
deploy/cloudrun.sh deploy     # builds both images (tagged with the git SHA), deploys api then web
```

It runs the equivalent of the following, which you can use as a reference or to run a single step by hand:

```bash
# Build (tag with the git SHA, never `latest`)
gcloud builds submit api --tag $REGION-docker.pkg.dev/$PROJECT_ID/amber/api:$GIT_SHA
gcloud builds submit ui --config ui/cloudbuild.yaml \
  --substitutions _IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/amber/web:$GIT_SHA,_API_ORIGIN=<API run.app URL>

# API
gcloud run deploy amber-api \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/amber/api:$GIT_SHA \
  --region $REGION --service-account amber-api@$PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated --ingress all --port 8000 \
  --add-cloudsql-instances $PROJECT_ID:$REGION:<instance> \
  --memory 1Gi --cpu 1 --timeout 3600 --concurrency 10 \
  --min-instances 0 --max-instances 3 \
  --env-vars-file <yaml of AMBER_* settings> \
  --set-secrets AMBER_GOOGLE_OAUTH_CLIENT_SECRET=amber-oauth-client-secret:latest,...

# Web
gcloud run deploy amber-web \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/amber/web:$GIT_SHA \
  --region $REGION --service-account amber-web@$PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated --memory 512Mi --timeout 3600 --min-instances 0 --max-instances 3 --port 3000 \
  --set-env-vars AMBER_API_ORIGIN=https://<amber-api run.app URL>
```

Cloud Run URLs are predictable (`amber-<service>-<project-number>.<region>.run.app`), so the script knows the API address before it exists and bakes it into the web image's `/api` rewrite. Confirm that the public URL matches `AMBER_PUBLIC_BASE_URL` and the registered redirect URI. Memory is 1 GiB with a 30 MB limit; raise it only if large files fail. Both services use `--timeout 3600` because Opal voice sessions are WebSockets (browser → web → api) and Cloud Run closes a WebSocket at the request timeout. Opal talks to Gemini Live directly (not LiteLLM) with the `amber-gemini-api-key` secret and `AMBER_GEMINI_LIVE_MODEL`, and sessions end after `AMBER_GEMINI_LIVE_MAX_SESSION_SECONDS` (default 1800). An open voice session holds one of an instance's 10 concurrent slots and keeps that instance billed while it is open.

**Cloud Scheduler (not covered by the script).** Drive sync needs two jobs, each a `POST` with the `X-Amber-Drive-Sync-Secret` header set to the `amber-drive-sync-secret` value. Without them, edited files are never re-indexed and Drive watch channels expire:

```bash
SECRET=$(gcloud secrets versions access latest --secret amber-drive-sync-secret)
gcloud scheduler jobs create http amber-drive-reindex --location $REGION --schedule "* * * * *" \
  --uri "$PUBLIC_URL/api/drive/sync/reindex-due" --http-method POST \
  --headers "X-Amber-Drive-Sync-Secret=$SECRET"
gcloud scheduler jobs create http amber-drive-renew --location $REGION --schedule "0 3 * * *" \
  --uri "$PUBLIC_URL/api/drive/sync/renew" --http-method POST \
  --headers "X-Amber-Drive-Sync-Secret=$SECRET"
```

---

## 10. Verification checklist (do all of it before inviting anyone)

1. `<web URL>/api/health` returns `{"status":"ok"}`.
2. Sign in with Google: no redirect-URI mismatch and no unverified-app warning. Consent shows only the basic and `drive.file` permissions.
3. Your bootstrap-admin email sees the Admin tab. A second account is a Member and gets 403 from `/api/admin/users`.
4. Pick a Doc and a PDF with the Google Picker and confirm they import. Browse into a folder in the Picker and multi-select several files. Upload a PDF, DOCX, PPTX and XLSX: each reaches "Ready" with a chunk count and appears in `Amber Uploads` in Drive.
5. Upload a file over the limit and confirm a clear error. Upload one near 30 MB to test the proxy path.
6. Upload an image-only PDF and confirm the "No readable text" error in the file's dropdown.
7. Share a file with a second account: Drive and Amber agree, and that account sees it in Manage Files without a Manage button.
8. Admin: add, deactivate and delete a user, view a document's access list, change chunk size and see the next upload change.
9. Cloud Logging shows no errors or secrets; the audit log has rows for admin actions.
10. Let both services idle to zero, then load the site and confirm sign-in still works after the cold start.
11. Ask a question in Quick and Chat mode, open a citation, and open "How this answer was built". A second account must not get answers from a file it can't open in Drive.
12. Edit an imported Doc in Drive, wait about 5 minutes, and confirm the document re-indexes (this checks both Cloud Scheduler jobs and the webhook). Remove a person from a file's sharing and confirm they lose it in Amber.
13. Start an Opal voice session and confirm it works through the web proxy.
14. If PostHog is configured, confirm a sign-in and a conversation show up as events.
15. Check the billing page after a day to compare with §7.

Rollback: shift traffic back to the previous revision (`gcloud run services update-traffic`). Schema changes are additive, so no database rollback is needed.

---

## 11. Remaining open items

1. **Delete the disabled folder-import code** (`/api/drive/folder-files`, `list_folder_files`, `can_import_folders` and their tests).
2. **Create the two Cloud Scheduler jobs** (§9) and add them to `deploy/cloudrun.sh`.
3. **Make the upload limit consistent** (§3): lower `LIMITS` in `api/amber/ingest/settings.py` to the real ceiling, or build the direct-to-Cloud-Storage upload.
4. **Pre-download the tiktoken vocabulary** in the API image (§4).
5. **Add CI/CD** (`.github/workflows/`) and a deployer service account once the manual deploy is routine.
6. **Read-only checks on the Cloud SQL instance** (§5.1) if the database has changed since they were last done: region, public IP, pgvector, Postgres version, and what data it holds.
7. **Billing budget:** confirm the $5 and $10 alerts exist.

## 12. Files added or changed for deployment

Done:
- `api/Dockerfile`, `api/.dockerignore`, `ui/Dockerfile`, `ui/.dockerignore`
- `ui/next.config.ts`: `output: "standalone"` and the proxy body-size setting (32 MB)
- `ui/cloudbuild.yaml`: builds the web image with the API address baked in
- `deploy/cloudrun.sh` and `deploy/cloudrun.env.example`
- **Picker work (§6):** `DRIVE_SCOPE` handling in `api/amber/models.py`, the picker-token endpoint in `api/amber/api/drive.py`, the Picker settings in `api/amber/util/config.py`, `ui/components/upload/drive-picker-panel.tsx` built around the Google Picker, the CSP update in `ui/proxy.ts`, and tests (`test_picker.py`)
- `ui/app/layout.tsx`: Google Search Console verification meta tag

Still open:
- `api/amber/ingest/settings.py` and the admin form: lower the upload ceiling to match the real limit
- tiktoken pre-download in `api/Dockerfile`
- a Cloud Scheduler step in `deploy/cloudrun.sh`
- `infra/scripts/` (idempotent, numbered) and `.github/workflows/` for CI/CD once the manual deploy works
