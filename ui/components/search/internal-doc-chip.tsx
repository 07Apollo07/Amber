"use client"

import { FileText, ExternalLink, ArrowUpRight } from "lucide-react"
import type { Source } from "@/lib/types"

export function InternalDocChip({
  text,
  href,
  sources,
  onOpenSource,
}: {
  text: string
  href?: string
  sources: Source[]
  onOpenSource: (source: Source) => void
}) {
  // Parse document ID and page from href or text
  // e.g., href = "http://localhost:3000/1." -> page 1
  // text = "Internal Doc bdc2c29f-2702-4a27-b705-fdd952f08f1f"
  const matchUuid = text.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i)
  const docId = matchUuid ? matchUuid[1] : "bdc2c29f-2702-4a27-b705-fdd952f08f1f"
  
  // Match page from href like /1. or /1 or page 1
  const matchPage = href?.match(/\/(\d+)(?:\.|$)/) || text.match(/page\s*(\d+)/i) || href?.match(/page[=-](\d+)/i)
  const page = matchPage ? Number(matchPage[1]) : 1

  const existingSource = sources.find((s) => s.documentId === docId || s.page === page)

  function handleClick() {
    const sourceToOpen: Source = existingSource || {
      n: sources.length + 1,
      documentId: docId,
      title: `Internal Document (${docId.slice(0, 8)})`,
      fileType: "pdf",
      origin: "desktop_upload",
      page: page,
      snippet: text,
      citedSpan: text.slice(0, 40),
      updatedAt: "2026-09-25",
      driveUrl: "#"
    }
    onOpenSource(sourceToOpen)
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className="group my-1 inline-flex items-center gap-2 rounded-xl border border-primary/30 bg-primary/5 px-3 py-1.5 text-left text-xs font-medium text-foreground transition-all hover:border-primary hover:bg-primary/10 hover:shadow-sm"
    >
      <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
        <FileText className="size-3.5" />
      </div>
      <div className="flex flex-col">
        <span className="font-semibold text-primary">
          Internal Doc ({docId.slice(0, 8)}…)
        </span>
        <span className="text-[11px] text-muted-foreground">
          Page {page} • Click to open PDF section
        </span>
      </div>
      <ExternalLink className="ml-1 size-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
    </button>
  )
}
