import { FileImage, FileSpreadsheet, FileText, Presentation, type LucideIcon } from "lucide-react"

import type { FileType } from "@/lib/types"
import { cn } from "@/lib/utils"

const icons: Record<FileType, { icon: LucideIcon; className: string }> = {
  pdf: { icon: FileText, className: "bg-red-500/10 text-red-300" },
  docx: { icon: FileText, className: "bg-sky-500/10 text-sky-300" },
  gdoc: { icon: FileText, className: "bg-sky-500/10 text-sky-300" },
  pptx: { icon: Presentation, className: "bg-orange-500/10 text-orange-300" },
  gslides: { icon: Presentation, className: "bg-amber-500/10 text-amber-300" },
  xlsx: { icon: FileSpreadsheet, className: "bg-emerald-500/10 text-emerald-300" },
  gsheet: { icon: FileSpreadsheet, className: "bg-emerald-500/10 text-emerald-300" },
  txt: { icon: FileText, className: "bg-muted text-muted-foreground" },
  md: { icon: FileImage, className: "bg-muted text-muted-foreground" },
}

export function FileIcon({ type, className }: { type: FileType; className?: string }) {
  const { icon: Icon, className: tone } = icons[type]
  return (
    <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg", tone, className)}>
      <Icon className="size-4" />
    </span>
  )
}
