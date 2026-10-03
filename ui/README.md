# Amber UI

Next.js 16 front end for Amber. Sign-in is real (Phase 2): Google sign-in with the Drive permission, handled by the API in `api`. Search, upload and admin data aren't connected yet. Those lists show empty states, and their buttons show a "demo only" toast (`demoAction` in `lib/demo.ts`).

```bash
cp .env.example .env.local   # AMBER_API_ORIGIN, defaults to http://127.0.0.1:8000
pnpm install
pnpm dev          # http://localhost:3000 (start the API first, see api/README.md)
pnpm lint && pnpm build
```

`/api/*` is rewritten to the API, so the browser only ever talks to one origin.

## Pages

| Route | What it shows |
|---|---|
| `/login` | Google sign-in and the Drive permission explainer |
| `/search` | Quick answer and Chat modes, filters, citations, source preview, trace panel, feedback |
| `/upload` | Desktop dropzone (saved to Drive), Drive Picker, sharing, collections/tags, upload status |
| `/profile` | Account, Drive connection, my documents (edit/delete), chat and search history |
| `/admin` | Documents, Users, Audit log, Query traces, Analytics, Settings |

## Auth in the web app

- `proxy.ts` sends signed-out visitors of `/search`, `/upload`, `/profile` and `/admin` to `/login?return_to=…`. It only checks that a session cookie exists.
- `app/(app)/layout.tsx` calls `requireUser()` (`lib/session.ts`). That asks the API's `/api/me`, which verifies the session and reads the role from Postgres.
- `/admin` renders only for admins, checked on the server.
- Sign-in, Reconnect and Connect Drive are plain links to `/api/auth/google/start`.
- Sign out, sign out everywhere and Disconnect Drive use `apiPost` (`lib/api.ts`), which sends the CSRF header.

## Security already in place

- Per-request nonce CSP in `proxy.ts`, plus HSTS, `X-Frame-Options: DENY`, `nosniff`, Referrer- and Permissions-Policy in `next.config.ts`.
- Answers render through `react-markdown` with `skipHtml` + `rehype-sanitize`; no `dangerouslySetInnerHTML`.
- No tokens or session data in `localStorage`. The session cookie is HttpOnly; JavaScript can only read the CSRF token.
