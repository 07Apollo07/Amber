import { Building2, Lock, UsersRound } from "lucide-react"

import type { Sharing } from "@/lib/types"

export function SharingSummary({ sharing }: { sharing: Sharing }) {
  if (sharing.kind === "private")
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Lock className="size-3.5" /> Private
      </span>
    )
  if (sharing.kind === "domain")
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Building2 className="size-3.5" /> @{sharing.domain}
      </span>
    )
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" title={sharing.emails.join(", ")}>
      <UsersRound className="size-3.5" /> {sharing.emails.length} {sharing.emails.length === 1 ? "person" : "people"}
    </span>
  )
}
