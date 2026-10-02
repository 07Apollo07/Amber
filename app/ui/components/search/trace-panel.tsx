"use client"

import { ChevronDown, EyeOff, Route } from "lucide-react"

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import type { Trace } from "@/lib/types"

/** Single-series meter: amber fill on a lighter step of the same hue. */
function ScoreMeter({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex items-center gap-2" title={`${label}: ${value.toFixed(2)}`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-chart-1/20" aria-hidden="true">
        <div className="h-full rounded-full bg-chart-1" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="text-xs text-foreground tabular-nums">{value.toFixed(2)}</span>
    </div>
  )
}

export function TracePanel({ trace, defaultOpen = false }: { trace: Trace; defaultOpen?: boolean }) {
  return (
    <Collapsible defaultOpen={defaultOpen} className="rounded-xl border bg-muted/20">
      <CollapsibleTrigger className="group flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-muted-foreground transition-colors hover:text-foreground">
        <Route className="size-4 text-primary" />
        <span className="font-medium">How this answer was built</span>
        <span className="ml-2 hidden text-xs sm:inline">
          {trace.chunks.length} passages · {(trace.latencyMs / 1000).toFixed(1)}s
        </span>
        <ChevronDown className="ml-auto size-4 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-4 border-t px-4 py-4 text-sm">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="text-xs text-muted-foreground">Your question</div>
              <div className="mt-0.5">{trace.query}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Searched as</div>
              <div className="mt-0.5 font-mono text-[13px] text-foreground/90">{trace.rewrittenQuery}</div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left">
              <caption className="sr-only">Retrieved passages and their scores</caption>
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="py-2 pr-3 font-medium">Passage</th>
                  <th className="py-2 pr-3 font-medium">Vector</th>
                  <th className="py-2 pr-3 font-medium">Keyword</th>
                  <th className="py-2 pr-3 font-medium">Rerank</th>
                  <th className="py-2 font-medium">Used</th>
                </tr>
              </thead>
              <tbody>
                {trace.chunks.map((chunk, i) => (
                  <tr key={i} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pr-3">
                      <span className="block max-w-[220px] truncate">{chunk.documentTitle}</span>
                      <span className="text-xs text-muted-foreground">Page {chunk.page}</span>
                    </td>
                    <td className="py-2 pr-3 text-xs tabular-nums">{chunk.vectorScore.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-xs tabular-nums">{chunk.keywordScore.toFixed(2)}</td>
                    <td className="py-2 pr-3">
                      <ScoreMeter value={chunk.rerankScore} label="Rerank score" />
                    </td>
                    <td className="py-2">
                      {chunk.cited ? (
                        <span className="rounded-md bg-success/15 px-1.5 py-0.5 text-xs font-medium text-success">Cited</span>
                      ) : (
                        <span className="text-xs text-muted-foreground">Not cited</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {trace.hiddenCount > 0 && (
            <div className="flex items-start gap-2 rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
              <EyeOff className="mt-0.5 size-3.5 shrink-0" />
              <span>
                {trace.hiddenCount} matching {trace.hiddenCount === 1 ? "document was" : "documents were"} hidden because
                you don&apos;t have access. Their content was never read.
              </span>
            </div>
          )}

          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
            <span>Model <span className="text-foreground">{trace.model}</span></span>
            <span>Latency <span className="text-foreground tabular-nums">{trace.latencyMs.toLocaleString()} ms</span></span>
            <span>
              Tokens <span className="text-foreground tabular-nums">{trace.promptTokens.toLocaleString()} in · {trace.completionTokens} out</span>
            </span>
            <span>Trace <span className="font-mono text-foreground">{trace.id}</span></span>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
