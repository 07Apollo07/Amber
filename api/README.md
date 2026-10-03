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

## Tests

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The tests never connect to a database or call Google or Firebase, so they're safe to run anywhere, at any time. They cover crypto, config validation, client-IP resolution, the sign-in redirect, return-to safety and security headers. Tests that wrote to a database or depended on timing were removed on purpose.
