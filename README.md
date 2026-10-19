# Amber

**Ask questions across your company's documents and get answers you can trust. Every employee sees only what they are already allowed to see in Google Drive.**

Amber is an open-source, enterprise-grade retrieval-augmented generation (RAG) app. People sign in with Google, bring in files from their computer or Google Drive, and ask questions in plain language. Amber answers with Gemini, cites the passages it used, and shows how the answer was built.

Its core rule is that **a result never includes a document the user isn't allowed to see**. Amber doesn't ask you to rebuild your permissions. It **pulls them from Google Drive**, keeps them in sync, and applies them to every search, so each employee gets answers only from the information they need and are cleared to access.

**Live:** [amber.kathalyst.ai](https://amber.kathalyst.ai)

**Demo video:** [YouTube](https://dub.kathalyst.ai/amber-video)

---

## Permissions come from Drive: need-to-know by default

Most AI search tools index everything and hope nobody asks the wrong question. That is a data leak waiting to happen: an intern asks about salaries, or a contractor asks about an acquisition, and the AI answers from files they could never open. Amber is built so that can't happen.

1. **Amber reads each file's sharing settings from Drive.** When a file is imported, Amber fetches its permissions (the people it is shared with, and whether it is shared with the whole company domain) and stores them as that document's access list.
2. **Every question is checked against that list.** The check runs inside the search query itself, before any text is retrieved. A document you can't open in Drive is never read, never sent to the model, and never quoted back to you.
3. **Permissions stay current.** Amber subscribes to Drive change notifications. If someone is removed from a file, or a file is unshared or trashed, Amber picks that up from Drive's change feed shortly after. You manage access in one place, Google Drive, and Amber follows.
4. **It is auditable.** Access, searches, sharing changes and admin actions are recorded in an append-only audit log.

| Scenario | What happens in Amber |
|---|---|
| HR shares a salary sheet with three people | Only those three can get answers drawn from it |
| A file is shared with the whole company domain | Anyone signed in with that domain can search it |
| A manager is removed from a Drive folder | They stop seeing its content in Amber's answers, with no separate cleanup |
| A contractor joins a single project folder | Their answers draw only on that project's documents |
| An employee leaves and their file is trashed | The file is no longer returned to anyone but its owner |

The result is a single source of truth for access (Drive) and an AI assistant that respects it, so each employee gets the information they need and nothing more.

## Why Amber

Company knowledge sits in Drive folders, shared docs, spreadsheets and PDFs. Finding an answer means remembering where it lives. Generic AI search tools can fix that, but they often ignore who is allowed to read what. Amber is built around that problem:

- **Need-to-know access, inherited from Drive.** Amber reads each file's sharing settings and uses them as its access list. If you can't open a file in Drive, Amber won't quote it to you.
- **Answers are traceable.** Every answer links back to its sources, and a trace shows the query rewrite, the retrieved passages and their scores, and which passages were cited.
- **Your documents stay in Drive.** Files uploaded from a desktop are also saved to the uploader's own Google Drive, which stays the home of the file and the source of its sharing.
- **Documents stay fresh.** Edits in Drive are picked up automatically, once a file has stopped changing for five minutes.

## Use cases

| Team | Example question |
|---|---|
| **Sales and customer success** | "What did we promise Acme in their last contract renewal?" |
| **Operations and HR** | "What is our parental leave policy for employees in India?" |
| **Legal and finance** | "Which vendor agreements auto-renew in Q1, and what are the notice periods?" Confidential contracts stay visible only to the people they are shared with. |
| **Product and engineering** | "Summarize the decisions in the last three architecture review docs." |
| **Onboarding** | "Where are the runbooks for the billing service?" |
| **Consultants and agencies** | Keep each client's documents in its own collection and share only what each person should see. |

## Features

**Search and chat**
- **Quick mode:** one answer plus ranked sources.
- **Chat mode:** multi-turn, streamed conversations with saved history, rename, and per-user access control.
- Filters by source, collection, file type and date. A side panel previews the source, and thumbs up/down feedback is recorded.
- **Hybrid retrieval:** vector search (pgvector, HNSW) combined with Postgres full-text keyword search.
- **Generative UI:** the agent can render charts, tables, KPI cards, comparisons, timelines and source cards from retrieved data.
- **Model choice:** Gemini by default; a model selector appears when a [LiteLLM](https://github.com/BerriAI/litellm) endpoint is configured.

**Documents**
- Drag-and-drop upload, or pick files with the Google Drive Picker.
- Google Docs, Sheets and Slides are exported and indexed alongside PDFs, Office files and text.
- Collections and tags, plus sharing on upload (private, specific people, or your whole domain).
- **Live sync with Drive:** permission changes are applied through Drive change notifications, and edited files are re-indexed after a quiet period.

**An agent that works in your Workspace**
- Searches indexed documents and reads files, Docs and Sheets.
- Creates folders and files, renames, moves, copies and shares in Drive, and reads or writes comments.
- Proposes edits to Docs and Sheets. **Every change pauses for your approval** in the chat before anything is written.
- Plans multi-step work in a live task list.

**Administration**
- Users and roles (Admin or Member), access and audit logs, analytics, and indexing settings.
- Documents management across the organization.
- Sharing is managed in Drive, so admins don't maintain a second set of permissions.
- An append-only audit log of access, searches, sharing changes and admin actions.

## Security model

- **Access control is part of the search query itself.** The search SQL checks each document's access list (copied from Drive) in the same query as the vector search, so hidden content is never fetched. Postgres Row-Level Security, forced even for the table owner, is an independent second check.
- **Per-document checks everywhere.** Opening a document, previewing a source or letting the agent read a file all go through the same access list, which guards against guessing IDs.
- **No tokens in the browser.** Google sign-in runs server-side (PKCE, state, nonce). The session is an HttpOnly Firebase session cookie, with CSRF protection on every state-changing request.
- **Refresh tokens are encrypted** with Cloud KMS (AES-256-GCM, bound to the user).
- **Least-privilege Drive access.** Amber requests only the `drive.file` scope: files you pick or that Amber creates, not your whole Drive.
- **Roles live in Postgres.** Client claims are never trusted, and sessions can be revoked immediately.

More detail is in [`api/README.md`](api/README.md) and [`PLAN.md`](PLAN.md).

## How to use Amber

1. **Sign in** at [amber.kathalyst.ai](https://amber.kathalyst.ai) with your Google account and approve the Drive permission.
2. **Add documents** on the **Upload** page: drag files in, or choose files from Google Drive.
3. **Organize** them into collections or tags, and set who can see them.
4. **Ask** on the **Search** page. Use Quick for a fast answer, or Chat to dig in with follow-up questions.
5. **Check the sources.** Open any citation to see the passage, and open "How this answer was built" for the full trace.
6. **Keep working in Drive.** Edit your files as usual. Amber updates its index shortly after your edits stop.
7. **Admins** manage users, review audit logs, and tune indexing from the **Admin** page.

## Architecture

| Part | Stack |
|---|---|
| `ui/` | Next.js 16, React, Tailwind, AI Elements, pnpm. Proxies `/api/*` to the API so cookies stay first-party |
| `api/` | FastAPI (Python 3.12), LangChain / LangGraph, psycopg2 with hand-written SQL |
| Data | Postgres with pgvector and full-text search |
| Models | Gemini via the Google AI API (`gemini-embedding-001` embeddings at 1536 dimensions) |
| Identity | Firebase Auth with Google sign-in |
| Hosting | Google Cloud Run, Cloud SQL, Secret Manager, Cloud KMS, Cloud Scheduler |

**How a Drive edit reaches the index**

```
Drive file edited ─▶ Drive webhook ─▶ Amber marks the file "changed" and restarts its 5-minute timer
                                      (permissions are re-synced immediately)
Cloud Scheduler, every minute ─▶ /api/drive/sync/reindex-due
                                      ─▶ files quiet for 5 minutes are downloaded and, if the content
                                         really changed, re-chunked and re-embedded
```

## Getting started (local development)

You need Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js with [pnpm](https://pnpm.io/), a Postgres database with the `pgvector` extension, a Firebase project with Google sign-in, a Google OAuth web client, and a Gemini API key.

```bash
# 1. Database: create the tables yourself. The app never creates or alters them.
psql "$DATABASE_URL" -f api/schema.sql

# 2. API
cd api
cp .env.example .env        # fill in the values; the file explains each one
uv sync
uv run python main.py       # http://127.0.0.1:8000

# 3. Web app (in another terminal)
cd ui
cp .env.example .env.local
pnpm install
pnpm dev                    # http://localhost:3000
```

Register `http://localhost:3000/api/auth/google/callback` as an authorized redirect URI on your OAuth client, and enable the Google Drive, Docs, Sheets and Picker APIs in your Cloud project.

Run the API tests (no database or Google access needed):

```bash
cd api && uv run pytest
```

## Deploying to Google Cloud

`deploy/cloudrun.sh` builds both services and deploys them to Cloud Run. Copy `deploy/cloudrun.env.example` to `deploy/cloudrun.env`, then run `setup`, `secrets` and `deploy` in that order. See [`DEPLOY.MD`](DEPLOY.MD) for the full walkthrough.

For Drive sync to work in production, create two Cloud Scheduler jobs that send a `POST` with the `X-Amber-Drive-Sync-Secret` header:

| Job | Schedule | Endpoint |
|---|---|---|
| Re-index changed files | every minute | `/api/drive/sync/reindex-due` |
| Renew Drive watches | daily | `/api/drive/sync/renew` |

Tune the quiet period with `AMBER_DRIVE_REINDEX_QUIET_SECONDS` (default 300) and `AMBER_DRIVE_REINDEX_MAX_WAIT_SECONDS` (default 3600).

## Project layout

```
api/        FastAPI backend: auth, ingestion, retrieval, agent, Drive sync
ui/         Next.js web app
deploy/     Cloud Run deployment script and config template
PLAN.md     Product and implementation plan
DEPLOY.MD   Google Cloud deployment guide
UNDERSTAND.MD  A guided reading order for the code
```

## Contributing

Contributions are welcome. Open an issue to discuss a bigger change first, keep pull requests focused, and add or update tests for behavior you change (`uv run pytest` in `api/`). Please don't include secrets, `.env` files or service-account keys in a PR.

## License

Licensed under the [Apache License, Version 2.0](LICENSE).

Built by [Anushka Singh](https://www.linkedin.com/in/asingh27) and [Justin Dsouza](https://www.linkedin.com/in/justin-dsouza07/).
