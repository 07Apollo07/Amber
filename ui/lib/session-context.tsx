"use client"

import { createContext, useContext, type ReactNode } from "react"

import type { SessionUser } from "./types"

const SessionContext = createContext<SessionUser | null>(null)

/** Provided by the signed-in layout; refreshed whenever the server re-renders (router.refresh()). */
export function SessionProvider({ user, children }: { user: SessionUser; children: ReactNode }) {
  return <SessionContext value={user}>{children}</SessionContext>
}

export function useSession(): SessionUser {
  const user = useContext(SessionContext)
  if (!user) throw new Error("useSession must be used inside the signed-in layout")
  return user
}
