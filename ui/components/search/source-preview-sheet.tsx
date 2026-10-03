"use client"

import { Download, ExternalLink } from "lucide-react"

import { FileIcon } from "@/components/app/file-icon"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { demoAction } from "@/lib/demo"
import { fileTypeLabel } from "@/lib/format"
import type { Source } from "@/lib/types"

function Highlighted({ text, span }: { text: string; span: string }) {
  const at = text.indexOf(span)
  if (at === -1) return <>{text}</>
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded bg-primary/25 px-0.5 text-foreground">{span}</mark>
      {text.slice(at + span.length)}
    </>
  )
}

export function SourcePreviewSheet({ source, onClose }: { source: Source | null; onClose: () => void }) {
  return (
    <Sheet open={source !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 sm:max-w-lg">
        {source && (
          <>
            <SheetHeader className="border-b pb-4">
              <div className="flex items-start gap-3 pr-8">
                <FileIcon type={source.fileType} className="size-10" />
                <div className="min-w-0">
                  <SheetTitle className="leading-snug">{source.title}</SheetTitle>
                  <SheetDescription className="mt-1">
                    Source {source.n} · Page {source.page} · {fileTypeLabel[source.fileType]}
                  </SheetDescription>
                </div>
              </div>
            </SheetHeader>

            <div className="flex-1 space-y-5 overflow-y-auto p-4">
              <section>
                <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">Cited passage</h3>
                <blockquote className="rounded-xl border bg-muted/40 p-4 text-sm leading-6">
                  <Highlighted text={source.snippet} span={source.citedSpan} />
                </blockquote>
              </section>

              <section>
                <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">Details</h3>
                <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
                  <dt className="text-muted-foreground">Origin</dt>
                  <dd>
                    <Badge variant="outline">{source.origin === "drive_picker" ? "Google Drive" : "Desktop upload"}</Badge>
                  </dd>
                  <dt className="text-muted-foreground">Last updated</dt>
                  <dd>{source.updatedAt}</dd>
                  <dt className="text-muted-foreground">Page</dt>
                  <dd>{source.page}</dd>
                </dl>
              </section>
            </div>

            <div className="flex gap-2 border-t p-4">
              <Button asChild className="flex-1">
                <a href={source.driveUrl} target="_blank" rel="noopener noreferrer">
                  <ExternalLink /> Open in Drive
                </a>
              </Button>
              <Button variant="outline" onClick={() => demoAction("Download")}>
                <Download /> Download
              </Button>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
