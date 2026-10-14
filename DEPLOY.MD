# Deploying Amber to Google Cloud

**Status: plan only. Nothing in this file has been run.** Commands are templates to review and run by hand, one step at a time.

## 0. Your answers and what they mean

| Your answer | Consequence for the plan |
|---|---|
| External app, used by companies on Google Workspace | Google's rules for restricted scopes apply (§6). This is the biggest risk to the plan. |
| Existing Cloud SQL instance, India region | Deploy Cloud Run in the **same region** (`asia-south1` Mumbai or `asia-south2` Delhi, whichever the instance is in). Cloud SQL has no free tier, so the instance you already pay for is your main fixed cost. |
| No custom domain yet | The app lives at a `*.run.app` URL. That rules out the load-balancer option (managed certificates need a domain). |
| Up to 200 MB uploads, later | **Decided: 30 MB for now** (§3). 200 MB is a future redesign. |
| Free tier, hobby project | No load balancer, no Cloud Armor, no minimum instances, no VPC connector (§7). |

**Decision: Option B** (two Cloud Run services, the web app proxies `/api` to the API). Options A and C are kept in §2 for when things change.

---

**Decisions made**

1. **Drive access:** narrow `drive.file` scope plus the Google Picker (§6). No Google verification needed.
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

There are no Dockerfiles or deploy scripts in the repo yet (§12 lists what will be added).

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

**Decision: 30 MB.** After deploy, set the max file size to 30 in Admin › Settings. The code change in §12 lowers the ceiling in `LIMITS` (`api/amber/ingest/settings.py`) and the form to 30, so nobody can enter a value that can't work.

**If you truly need 200 MB later**, it's a feature, not a config change: the browser uploads straight to a Cloud Storage bucket with a signed resumable URL, and the API then reads from the bucket and indexes in the background (Cloud Tasks), with 4–8 GiB of memory for the worker. The bucket is free only in `us-*` regions (5 GB), so in India it costs a few cents a month. Say if you want this designed.

---

## 4. Things in the code to fix before the first deploy

1. **Add Dockerfiles** and `.dockerignore` files (exclude `.env`, `.venv`, `node_modules`, `.next`, key files).
2. **`output: "standalone"`** in `ui/next.config.ts`, plus `experimental.proxyClientMaxBodySize` set to match the upload limit.
3. **API start command:** `uvicorn main:create_app --factory --host 0.0.0.0 --port $PORT --no-proxy-headers`. `main.run()` binds `127.0.0.1` and reads `AMBER_PORT`, so don't use it in the container.
4. **tiktoken downloads its vocabulary at runtime** (`cl100k_base`). Download it during the image build and set `TIKTOKEN_CACHE_DIR`, or the first upload on each cold instance is slow or fails.
5. **Database connections.** Each request opens its own connection (`db.py`), and sign-in checks open two. Small Cloud SQL tiers allow only a few dozen connections, so cap the API at `--max-instances 3` and `--concurrency 10`.
6. **Per-instance rate limits** only. Fine for now.
7. **Search and chat aren't built**, so this deploy covers upload, Manage Files, Drive import, profile and admin.

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
6. **Known gap:** `document_access` has row-level security on but no policy, so a role subject to RLS can't read it. While the app's database user is the table owner, RLS is bypassed and the explicit SQL filters do the protecting. Check which role `amber_app` is before relying on this; don't change to a stricter role without adding and testing policies.

---

## 6. Google sign-in and Drive access (decided: `drive.file` + Picker)

**Why:** the current full `drive` scope is restricted. For an External app that means a 100-user cap, an "unverified app" warning, 7-day refresh tokens in Testing mode, and verification that needs a domain you own and a paid annual security review. `drive.file` is not restricted, so none of that applies.

**What `drive.file` allows:** Amber can see only files it created (everything uploaded to `Amber Uploads`) and files the user explicitly picks in the Google Picker. It can change sharing on those files. It can no longer browse the user's whole Drive.

**Consent screen:** scopes `openid`, `email`, `profile` and `drive.file` only. Set publishing status to **In production**, because Testing mode expires tokens after 7 days. No sensitive or restricted scopes means no verification is required, but check the console, since Google may still ask for basic branding details.

**Code changes this needs (not done yet, see §12):**
1. `api/amber/models.py`: change `DRIVE_SCOPE` to `drive.file`; `can_manage_drive_sharing` then accepts it. Users whose stored token has the old scope are sent through consent again at their next sign-in (the existing re-consent flow handles this).
2. **Picker token endpoint:** the Google Picker runs in the browser and needs an OAuth access token plus a Picker developer key and the Cloud project number as the "app ID" (the app ID is what makes picked files readable under `drive.file`). Add `GET /api/drive/picker-token`, which returns a short-lived access token (about one hour) minted from the stored refresh token. The refresh token itself still never reaches the browser. The token is limited to `drive.file`, which is the least that can work. Create a browser API key restricted to the web origin and to the Picker API.
3. **UI:** replace the custom Drive browser in `drive-picker-panel.tsx` with Google's Picker (loaded from `apis.google.com`). Picked file IDs go to the existing `/api/drive/import` endpoint.
4. **Remove** `GET /api/drive/files` (the Drive browsing endpoint), since the scope no longer permits it.
5. **CSP:** `ui/proxy.ts` sets a strict nonce-based Content-Security-Policy. It must allow Google's Picker script and frames (`apis.google.com`, `docs.google.com`, `*.google.com`, and `*.googleusercontent.com` for thumbnails). Add only what the Picker needs, and test in the browser.
6. **Behavior to expect:**
   - Files imported earlier under the full scope may stop allowing sharing changes until the user re-picks them. Show the existing Drive error message clearly.
   - Importing a file the user can only view (not own) may fail when reading its permission list. The importer already reports per-file failures.
   - Google Docs, Sheets and Slides still export to Office formats once picked.

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
| Secret Manager | 6 active versions | 5 secrets | Fits (keep one version each) |
| Firebase Auth (Google sign-in) | Free | Sign-in | Fits |
| Cloud Logging | 50 GiB/month | Low | Fits |
| Cloud KMS | None, ~$0.06 per key version/month | Token encryption key (**required in prod**) | A few cents |
| Cloud SQL | **None** | Existing instance | Already paid; a new database on it adds only storage |
| Load balancer, Cloud Armor | None | Not used in Option B | Skipped |
| Outbound traffic | Small free amount | Pages and uploads | Pennies at hobby volume |
| Gemini API | Not used (billed key, decided) | Embeddings | Small per-token cost; covered by the budget alert |

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
2. **Enable APIs:** Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud KMS, Cloud SQL Admin, IAM Credentials, Drive, Google Picker, Generative Language, Identity Toolkit. Create the restricted Picker browser API key.
3. **Artifact Registry:** one Docker repository `amber` in `$REGION`.
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
   | `amber-gemini-api-key` | `AMBER_GEMINI_API_KEY` |
   | `amber-state-cookie-key` | `AMBER_STATE_COOKIE_KEY` (a new Fernet key, not the dev one) |
   | `amber-database-dsn` | `AMBER_DATABASE_DSN` |

   Plain env vars: `AMBER_ENV=prod`, `AMBER_PUBLIC_BASE_URL=https://amber-web-<project-number>.<region>.run.app`, `AMBER_COOKIE_SECURE=true`, `AMBER_GOOGLE_OAUTH_CLIENT_ID`, `AMBER_FIREBASE_PROJECT_ID`, `AMBER_TOKEN_KMS_KEY`, `AMBER_BOOTSTRAP_ADMIN_EMAILS`, plus the Picker API key and project number (new settings added by the §6 code change). Leave `AMBER_TRUSTED_PROXIES` empty at first (audit-log IPs will show the proxy, not the user).

---

## 9. Build and deploy

```bash
# Build (tag with the git SHA, never `latest`)
gcloud builds submit api --tag $REGION-docker.pkg.dev/$PROJECT_ID/amber/api:$GIT_SHA
gcloud builds submit ui  --tag $REGION-docker.pkg.dev/$PROJECT_ID/amber/web:$GIT_SHA

# API
gcloud run deploy amber-api \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/amber/api:$GIT_SHA \
  --region $REGION --service-account amber-api@$PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated --ingress all \
  --add-cloudsql-instances $PROJECT_ID:$REGION:<instance> \
  --memory 1Gi --cpu 1 --timeout 300 --concurrency 10 \
  --min-instances 0 --max-instances 3 \
  --set-env-vars AMBER_ENV=prod,AMBER_PUBLIC_BASE_URL=...,... \
  --set-secrets AMBER_GOOGLE_OAUTH_CLIENT_SECRET=amber-oauth-client-secret:latest,...

# Web (set AMBER_API_ORIGIN to the API's run.app URL)
gcloud run deploy amber-web \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/amber/web:$GIT_SHA \
  --region $REGION --service-account amber-web@$PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated --memory 512Mi --min-instances 0 --max-instances 3 \
  --set-env-vars AMBER_API_ORIGIN=https://<amber-api run.app URL>
```

Order: build both, deploy the API, read its URL, deploy the web app with that URL, then confirm the web URL matches `AMBER_PUBLIC_BASE_URL` and the registered redirect URI. Memory is 1 GiB with a 30 MB limit; raise it only if large files fail.

---

## 10. Verification checklist (do all of it before inviting anyone)

1. `<web URL>/api/health` returns `{"status":"ok"}`.
2. Sign in with Google: no redirect-URI mismatch and no unverified-app warning. Consent shows only the basic and `drive.file` permissions.
3. Your bootstrap-admin email sees the Admin tab. A second account is a Member and gets 403 from `/api/admin/users`.
4. Pick a Doc and a PDF with the Google Picker and confirm they import. Upload a PDF, DOCX, PPTX and XLSX: each reaches "Ready" with a chunk count and appears in `Amber Uploads` in Drive.
5. Upload a file over the limit and confirm a clear error. Upload one near 30 MB to test the proxy path.
6. Upload an image-only PDF and confirm the "No readable text" error in the file's dropdown.
7. Share a file with a second account: Drive and Amber agree, and that account sees it in Manage Files without a Manage button.
8. Admin: add, deactivate and delete a user, view a document's access list, change chunk size and see the next upload change.
9. Cloud Logging shows no errors or secrets; the audit log has rows for admin actions.
10. Let both services idle to zero, then load the site and confirm sign-in still works after the cold start.
11. Check the billing page after a day to compare with §7.

Rollback: shift traffic back to the previous revision (`gcloud run services update-traffic`). Schema changes are additive, so no database rollback is needed.

---

## 11. Remaining open items

All four decisions are made (§0). What's left before anyone runs anything:

1. **Read-only checks on the Cloud SQL instance** (§5.1): region, public IP, pgvector, Postgres version, and what data the current database holds.
2. **Approve the code changes** in §12. I have not started them.
3. **Google project number and region**, to fix the `run.app` URL and register the OAuth redirect URI.
4. **Billing budget:** OK to set $5 / $10 alerts?

## 12. Files this plan will add or change when you approve

- `api/Dockerfile`, `api/.dockerignore`, `ui/Dockerfile`, `ui/.dockerignore`
- `ui/next.config.ts`: `output: "standalone"` and the proxy body-size setting (about 32 MB)
- `api/amber/ingest/settings.py` and the admin form: upload ceiling lowered to 30 MB
- **Picker work (§6):** `DRIVE_SCOPE` change in `api/amber/models.py`, a picker-token endpoint in `api/amber/api/drive.py`, new Picker settings in `api/amber/util/config.py`, `ui/components/upload/drive-picker-panel.tsx` rewritten around the Google Picker, CSP update in `ui/proxy.ts`, tests for the token endpoint and scope handling
- `infra/scripts/` (idempotent, numbered) and `.github/workflows/` for CI/CD once the manual deploy works
