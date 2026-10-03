import { ExternalLink } from "lucide-react"

import { FileIcon } from "@/components/app/file-icon"
import type { Source } from "@/lib/types"

export function SourceList({ sources, onOpen }: { sources: Source[]; onOpen: (n: number) => void }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">Sources</h3>
      <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {sources.map((source) => (
          <li key={source.n}>
            <button
              type="button"
              onClick={() => onOpen(source.n)}
              className="group flex w-full items-start gap-3 rounded-xl border bg-card/60 p-3 text-left transition-colors hover:border-primary/40 hover:bg-card"
            >
              <FileIcon type={source.fileType} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  <span className="text-primary">{source.n}</span>
                  <span className="truncate">{source.title}</span>
                </span>
                <span className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{source.snippet}</span>
                <span className="mt-1.5 flex items-center gap-1 text-[11px] text-muted-foreground/80">
                  Page {source.page} · {source.origin === "drive_picker" ? "Google Drive" : "Uploaded"}
                  <ExternalLink className="ml-auto size-3 opacity-0 transition-opacity group-hover:opacity-100" />
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  )
}
