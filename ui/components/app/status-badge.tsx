import { CircleAlert, CircleCheck, Clock, CloudUpload, FileSearch, Loader2, type LucideIcon } from "lucide-react"

import { statusLabel } from "@/lib/format"
import type { IngestionStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

const styles: Record<IngestionStatus, { icon: LucideIcon; className: string; spin?: boolean }> = {
  queued: { icon: Clock, className: "bg-muted text-muted-foreground" },
  saving_to_drive: { icon: CloudUpload, className: "bg-info/15 text-info" },
  parsing: { icon: FileSearch, className: "bg-info/15 text-info" },
  embedding: { icon: Loader2, className: "bg-primary/15 text-primary", spin: true },
  ready: { icon: CircleCheck, className: "bg-success/15 text-success" },
  failed: { icon: CircleAlert, className: "bg-destructive/15 text-destructive" },
}

/** Status always pairs an icon with a text label, never color alone. */
export function StatusBadge({ status }: { status: IngestionStatus }) {
  const { icon: Icon, className, spin } = styles[status]
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium whitespace-nowrap", className)}>
      <Icon className={cn("size-3.5", spin && "animate-spin")} />
      {statusLabel[status]}
    </span>
  )
}
