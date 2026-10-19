"use client"

import { createContext, useContext } from "react"

type AdminNav = {
  /** Switches to another admin tab. */
  showTab: (tab: string) => void
  /** Switches to the Query traces tab and opens this trace. */
  openTrace: (traceId: string) => void
  /** A trace another tab asked to open, until the Traces tab shows it. */
  requestedTraceId: string | null
  clearRequestedTrace: () => void
}

export const AdminNavContext = createContext<AdminNav>({
  showTab: () => undefined,
  openTrace: () => undefined,
  requestedTraceId: null,
  clearRequestedTrace: () => undefined,
})

export function useAdminNav(): AdminNav {
  return useContext(AdminNavContext)
}
