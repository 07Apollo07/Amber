"use client"

import { Building2, ExternalLink, Lock, Settings2, UsersRound, X } from "lucide-react"

import { StatusBadge } from "@/components/app/status-badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { formatBytes } from "@/lib/format"
import type { Sharing, UploadRow } from "@/lib/types"

export function sharingLabel(sharing: Sharing) {
  if (sharing.kind === "domain") return { icon: Building2, text: `Everyone at @${sharing.domain}` }
  if (sharing.kind === "people") {
    const n = sharing.emails.length
    return { icon: UsersRound, text: `${n} ${n === 1 ? "person" : "people"}` }
  }
  return { icon: Lock, text: "Only you" }
}

/** One document in the Manage Files list. Uploads that haven't reached the server show progress instead of Manage. */
export function FileRow({
  row,
  onRemove,
  onManage,
}: {
  row: UploadRow
  onRemove: (id: string) => void
  onManage: (row: UploadRow) => void
}) {
  const inProgress = row.status !== "ready" && row.status !== "failed"
  const { icon: ShareIcon, text } = sharingLabel(row.sharing)
  return (
    <li className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium">{row.name}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(row.sizeBytes)}</span>
        </div>
        {row.error ? (
          <p className="mt-1 text-xs text-destructive">{row.error}</p>
        ) : inProgress ? (
          <Progress value={row.progress} className="mt-2 h-1.5" aria-label={`${row.name} progress`} />
        ) : null}
        {row.saved && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <ShareIcon className="size-3.5" /> {text}
            </span>
            {row.tags.map((tag) => (
              <span key={tag} className="rounded-full border px-2 py-0.5">
                #{tag}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 sm:justify-end">
        <StatusBadge status={row.status} />
        {row.driveUrl && (
          <Button variant="ghost" size="icon-sm" asChild>
            <a href={row.driveUrl} target="_blank" rel="noopener noreferrer" aria-label={`Open ${row.name} in Drive`}>
              <ExternalLink />
            </a>
          </Button>
        )}
        {row.saved && (
          <Button variant="outline" size="sm" onClick={() => onManage(row)}>
            <Settings2 /> Manage
          </Button>
        )}
        {!row.saved && !inProgress && (
          <Button variant="ghost" size="icon-sm" aria-label={`Dismiss ${row.name}`} onClick={() => onRemove(row.id)}>
            <X />
          </Button>
        )}
      </div>
    </li>
  )
}
