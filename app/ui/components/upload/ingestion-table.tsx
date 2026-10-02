"use client"

import { ExternalLink, Inbox, RotateCw, X } from "lucide-react"

import { EmptyState } from "@/components/app/empty-state"
import { StatusBadge } from "@/components/app/status-badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { demoAction } from "@/lib/demo"
import { formatBytes } from "@/lib/format"
import type { UploadRow } from "@/lib/types"

export function IngestionTable({ rows, onRemove }: { rows: UploadRow[]; onRemove: (id: string) => void }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No uploads yet"
        description="Files you add will show their progress here."
        className="rounded-2xl border border-dashed"
      />
    )
  }

  return (
    <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border bg-card/40">
      {rows.map((row) => {
        const inProgress = row.status !== "ready" && row.status !== "failed"
        return (
          <li key={row.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
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
            </div>
            <div className="flex items-center gap-2 sm:w-[300px] sm:justify-end">
              <StatusBadge status={row.status} />
              {row.driveUrl && (
                <Button variant="ghost" size="sm" asChild>
                  <a href={row.driveUrl} target="_blank" rel="noopener noreferrer">
                    <ExternalLink /> Open in Drive
                  </a>
                </Button>
              )}
              {row.status === "failed" && (
                <Button variant="outline" size="sm" onClick={() => demoAction("Retry upload")}>
                  <RotateCw /> Retry
                </Button>
              )}
              {!inProgress && (
                <Button variant="ghost" size="icon-sm" aria-label={`Dismiss ${row.name}`} onClick={() => onRemove(row.id)}>
                  <X />
                </Button>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
