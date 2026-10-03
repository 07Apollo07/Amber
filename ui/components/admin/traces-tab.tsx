"use client"

import { useState } from "react"
import { EyeOff, ThumbsDown, ThumbsUp } from "lucide-react"

import { TracePanel } from "@/components/search/trace-panel"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { QueryTraceRow as TraceRow } from "@/lib/types"

// Loaded from the traces API once it exists.
const traces: TraceRow[] = []

function Feedback({ value }: { value: TraceRow["feedback"] }) {
  if (value === "up")
    return (
      <span className="inline-flex items-center gap-1 text-xs text-success">
        <ThumbsUp className="size-3.5" /> Helpful
      </span>
    )
  if (value === "down")
    return (
      <span className="inline-flex items-center gap-1 text-xs text-destructive">
        <ThumbsDown className="size-3.5" /> Not helpful
      </span>
    )
  return <span className="text-xs text-muted-foreground">None</span>
}

export function TracesTab() {
  const [open, setOpen] = useState<TraceRow | null>(null)

  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-2xl border bg-card/40">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Question</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Time</TableHead>
              <TableHead className="text-right">Latency</TableHead>
              <TableHead>Hidden</TableHead>
              <TableHead>Feedback</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {traces.map((t) => (
              <TableRow key={t.id} className="cursor-pointer" onClick={() => setOpen(t)}>
                <TableCell className="max-w-[280px] pl-4">
                  <button type="button" className="truncate text-left font-medium hover:text-primary" onClick={() => setOpen(t)}>
                    {t.query}
                  </button>
                </TableCell>
                <TableCell className="text-muted-foreground">{t.user}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{t.at}</TableCell>
                <TableCell className="text-right tabular-nums">{(t.latencyMs / 1000).toFixed(1)}s</TableCell>
                <TableCell>
                  {t.hiddenCount > 0 ? (
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <EyeOff className="size-3.5" /> {t.hiddenCount}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">0</span>
                  )}
                </TableCell>
                <TableCell>
                  <Feedback value={t.feedback} />
                </TableCell>
              </TableRow>
            ))}
            {traces.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                  No questions have been asked yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="w-full sm:max-w-2xl">
          {open && (
            <>
              <SheetHeader>
                <SheetTitle>{open.query}</SheetTitle>
                <SheetDescription>
                  {open.user} · {open.at} · trace {open.id}
                </SheetDescription>
              </SheetHeader>
              <div className="space-y-3 overflow-y-auto px-4 pb-4">
                <TracePanel trace={open} defaultOpen />
                <p className="text-xs text-muted-foreground">
                  Passage text from documents you can&apos;t access is redacted. Admins see metadata and scores only.
                </p>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}
