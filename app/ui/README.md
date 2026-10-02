# Amber UI

Next.js 16 front end for Amber (Phase 1: UI only). There is no data yet: every list, table and chart shows its empty state until the API is connected, and no one is signed in. Buttons that would call the API show a "demo only" toast instead (`demoAction` in `lib/demo.tsx`).

```bash
pnpm install
pnpm dev          # http://localhost:3000
pnpm lint && pnpm build
```

## Pages

| Route | What it shows |
|---|---|
| `/login` | Google sign-in and the Drive permission explainer |
| `/search` | Quick answer and Chat modes, filters, citations, source preview, trace panel, feedback |
| `/upload` | Desktop dropzone (saved to Drive), Drive Picker, sharing, collections/tags, upload status |
| `/profile` | Account, Drive connection, my documents (edit/delete), chat and search history |
| `/admin` | Documents, Users, Audit log, Query traces, Analytics, Settings |

## Demo controls

- **Role:** account menu → *Demo: view as* Admin / Member. Members don't see Admin.
- **Drive connection:** Profile → *Disconnect* / *Connect*. Upload is blocked while Drive is disconnected.

## Security already in place

- Per-request nonce CSP in `proxy.ts`, plus HSTS, `X-Frame-Options: DENY`, `nosniff`, Referrer- and Permissions-Policy in `next.config.ts`.
- Answers render through `react-markdown` with `skipHtml` + `rehype-sanitize`; no `dangerouslySetInnerHTML`.
- No tokens or session data in `localStorage`.
