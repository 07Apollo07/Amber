Here's how to set up Firebase and Google and fill in every setting the code reads.

The API reads its settings from `AMBER_*` variables in `app/api/.env`; `app/api/.env.example` is the template. The web app needs one variable in `app/ui/.env.local`. You don't need any `NEXT_PUBLIC_FIREBASE_*` variables: the API does the whole Firebase exchange on the server, so the browser never loads the Firebase SDK.

Google's console menu names change occasionally, so the labels below may differ slightly.

---

## Part 1 — Firebase project

1. **Open your project.** At console.firebase.google.com, open your existing project. Its Google Cloud project is the same project, under the same ID.
2. **Copy the project ID.** Go to ⚙️ **Project settings → General**. **Project ID** → `AMBER_FIREBASE_PROJECT_ID`.
3. **Copy the Web API key.** On the same page, **Web API Key** → `AMBER_FIREBASE_WEB_API_KEY`. If no key appears, click **Add app → Web (</>)** to register a web app, and the key will show up. You only need the key; ignore the JS config snippet.
4. **Turn on Google sign-in.** Go to **Build → Authentication → Sign-in method → Add new provider → Google**, enable it, set a support email, and save.
5. **Copy the client ID and secret.** In that Google provider panel, expand **Web SDK configuration** and copy:
   - **Web client ID** → `AMBER_GOOGLE_OAUTH_CLIENT_ID`
   - **Web client secret** → `AMBER_GOOGLE_OAUTH_CLIENT_SECRET`

   Use this exact client, not a new one. Firebase only accepts Google sign-ins issued for a client it knows about.
6. **Add your domains.** Go to **Authentication → Settings → Authorized domains**. `localhost` is usually already there; add your production domain when you have one.

## Part 2 — Google Cloud console (same project)

7. **Add the redirect URIs.** Open console.cloud.google.com → **APIs & Services → Credentials**. Open the OAuth client from step 5, usually named *"Web client (auto created by Google Service)"*. Under **Authorized redirect URIs**, add:
   - `http://localhost:3000/api/auth/google/callback`
   - `https://<your-domain>/api/auth/google/callback` (later, for production)

   These must match `AMBER_PUBLIC_BASE_URL` + `/api/auth/google/callback` exactly, or Google rejects sign-in with a redirect-URI mismatch.
8. **Set up the OAuth consent screen.** It's under **Google Auth Platform**, or **APIs & Services → OAuth consent screen**.
   1. **Branding:** app name, support email, developer contact.
   2. **Audience:** **External**, since anyone with a Google account can sign in. While it's in **Testing**, add your own Google account as a test user.
   3. **Data access / Scopes:** add `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` and `https://www.googleapis.com/auth/drive.file`.

   `drive.file` was chosen to avoid the costly security review Google requires for broad Drive access. To publish beyond test users, you may still need basic brand verification.
9. **Enable the APIs** under **APIs & Services → Library**:
   - **Identity Toolkit API** (Firebase Auth usually enables it already)
   - **Google Drive API** (needed from Phase 4, harmless now)
   - **Cloud Key Management Service (KMS) API**, if you use KMS in step 12

## Part 3 — Credentials for the Firebase Admin SDK

10. **Give the API Google credentials.** The API uses `firebase-admin` with Application Default Credentials, so it needs no JSON key file.
    - **Locally:** run `gcloud auth application-default login`, then `gcloud auth application-default set-quota-project <project-id>`. The Google account you use needs the **Firebase Authentication Admin** role, or Owner/Editor on the project.
      - Earlier, `gcloud` failed on this machine because it ran under Python 3.14. Point it at Python 3.12 first: `export CLOUDSDK_PYTHON=$(uv python find 3.12)`.
    - **On Cloud Run:** run the API under its own service account with `roles/firebaseauth.admin`, and with `roles/cloudkms.cryptoKeyEncrypterDecrypter` on the KMS key if you use one.

## Part 4 — Secrets you generate yourself

11. **State-cookie key** → `AMBER_STATE_COOKIE_KEY`:
    ```bash
    cd app/api && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ```
12. **Token-encryption key.** This encrypts users' stored Drive tokens. Pick one option:
    - **Dev only:** generate a local key → `AMBER_LOCAL_TOKEN_KEY`:
      ```bash
      uv run python -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
      ```
    - **Recommended, and required in prod:** create a Cloud KMS key ring and a symmetric key, then set `AMBER_TOKEN_KMS_KEY=projects/<project>/locations/<region>/keyRings/<ring>/cryptoKeys/<key>`.

## Part 5 — The remaining settings

13. **Finish `app/api/.env`:**
    ```
    AMBER_ENV=dev
    AMBER_PUBLIC_BASE_URL=http://localhost:3000
    AMBER_GOOGLE_OAUTH_CLIENT_ID=...          # step 5
    AMBER_GOOGLE_OAUTH_CLIENT_SECRET=...      # step 5
    AMBER_FIREBASE_PROJECT_ID=...             # step 2
    AMBER_FIREBASE_WEB_API_KEY=...            # step 3
    AMBER_STATE_COOKIE_KEY=...                # step 11
    AMBER_LOCAL_TOKEN_KEY=...                 # step 12 (or AMBER_TOKEN_KMS_KEY)
    AMBER_DATABASE_DSN=postgresql://amber_app@127.0.0.1:5432/amber_dev
    AMBER_BOOTSTRAP_ADMIN_EMAILS=you@yourdomain.com
    AMBER_TRUSTED_PROXIES=127.0.0.1/32
    # AMBER_COOKIE_SECURE=false   # only if you develop in Safari
    ```
    - **Bootstrap admin:** this only makes you admin the *first* time that account signs in. If you've already signed in, change your `role` to `admin` in the `users` table directly.
    - **Missing values:** the API now refuses to start if any required value is missing, and the error names the missing setting.
14. **Web app:** create `app/ui/.env.local` with:
    ```
    AMBER_API_ORIGIN=http://127.0.0.1:8000
    ```
15. **Create the database tables** in `amber_dev` using `app/api/schema.sql` as the reference: `users`, `oauth_tokens`, `audit_log` and **`revoked_sessions`**, plus the `amber_app` grants.

## Part 6 — Run it

16. Start the API:
    ```bash
    cd app/api && uv sync && uv run uvicorn amber.main:create_app --factory --reload --port 8000
    ```
17. Start the web app (`cd app/ui && pnpm dev`) and open **http://localhost:3000**. Click **Continue with Google** and approve the consent screen, which includes the Drive permission. You should land on `/search` signed in, and Profile should show Google Drive as **Connected**.

**If something goes wrong:**
- **`redirect_uri_mismatch`:** fix step 7 so it matches `AMBER_PUBLIC_BASE_URL` exactly.
- **`/login?error=firebase`:** usually the client from step 5 isn't the one Firebase's Google provider uses, or the Web API key is wrong.
- **Sign-in works but every page sends you back to login:** the API can't verify sessions. Check the credentials from step 10, and that the account has the Firebase Auth Admin role.
- **`access_denied`:** add your Google account as a test user (step 8.2) while the app is in Testing.







```js
// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAnalytics } from "firebase/analytics";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyD6YbojcIA6OFjvo3-ya4yoweYQTpr2ZsQ",
  authDomain: "amber-510307.firebaseapp.com",
  projectId: "amber-510307",
  storageBucket: "amber-510307.firebasestorage.app",
  messagingSenderId: "858129040366",
  appId: "1:858129040366:web:02d8e032c82411fa9a04ff",
  measurementId: "G-1B200QCYHV"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);
```