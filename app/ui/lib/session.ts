import { cookies } from "next/headers"
import { redirect } from "next/navigation"
import { cache } from "react"

import { SESSION_COOKIES } from "./auth-paths"
import type { SessionUser } from "./types"

/** Where the Next.js server reaches FastAPI (the same service the /api rewrite points at). */
function apiOrigin(): string {
  return process.env.AMBER_API_ORIGIN ?? "http://127.0.0.1:8000"
}

type SessionResult = { user: SessionUser } | { user: null; reason: "signed_out" | "deactivated" }

/**
 * Resolves the session by asking the API (which verifies the Firebase session cookie and
 * reads the role from Postgres). Cached per request.
 */
export const getSession = cache(async (): Promise<SessionResult> => {
  const jar = await cookies()
  const session = SESSION_COOKIES.map((name) => jar.get(name)).find(Boolean)
  if (!session) return { user: null, reason: "signed_out" }

  const res = await fetch(`${apiOrigin()}/api/me`, {
    headers: { cookie: `${session.name}=${session.value}` },
    cache: "no-store",
  })
  if (res.status === 401) return { user: null, reason: "signed_out" }
  if (res.status === 403) return { user: null, reason: "deactivated" }
  if (!res.ok) throw new Error(`GET /api/me failed with ${res.status}`)
  return { user: (await res.json()) as SessionUser }
})

/** For signed-in pages: returns the user or redirects to /login. */
export async function requireUser(): Promise<SessionUser> {
  const session = await getSession()
  if (session.user) return session.user
  redirect(session.reason === "deactivated" ? "/login?error=deactivated" : "/login")
}
