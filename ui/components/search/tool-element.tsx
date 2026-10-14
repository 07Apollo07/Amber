"use client"

import { useState } from "react"
import { Wrench, CheckCircle2, XCircle, Loader2, ChevronDown, ChevronRight, Terminal } from "lucide-react"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"
import type { ToolCallTrace } from "@/lib/types"

function linkifyText(text: string) {
  if (!text) return null
  const urlRegex = /(https?:\/\/[^\s]+)/g
  const parts = text.split(urlRegex)
  return parts.map((pathItem, i) => {
    let part = pathItem
    if (part.match(urlRegex)) {
      let cleanUrl = part
      while (/[\]\)\.,;:]$/.test(cleanUrl)) {
        cleanUrl = cleanUrl.slice(0, -1)
      }
      const trailing = part.slice(cleanUrl.length)
      return (
        <span key={i}>
          <a
            href={cleanUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline hover:underline break-all font-sans"
          >
            {cleanUrl}
          </a>
          {trailing}
        </span>
      )
    }
    return part
  })
}

export function ToolElement({ tool }: { tool: ToolCallTrace }) {
  const [isOpen, setIsOpen] = useState(false)
  const [resultOpen, setResultOpen] = useState(false)

  const isRunning = tool.status === "running"
  const isSuccess = tool.status === "success"
  const isFailed = tool.status === "failed"

  return (
    <div className="rounded-xl border bg-card/60 text-card-foreground shadow-xs transition-all">
      <div className="flex items-center justify-between px-3 py-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <div className={cn(
            "flex size-6 shrink-0 items-center justify-center rounded-lg border",
            isRunning && "bg-amber-500/10 border-amber-500/30 text-amber-500",
            isSuccess && "bg-success/10 border-success/30 text-success",
            isFailed && "bg-destructive/10 border-destructive/30 text-destructive",
          )}>
            {isRunning && <Loader2 className="size-3.5 animate-spin" />}
            {isSuccess && <CheckCircle2 className="size-3.5" />}
            {isFailed && <XCircle className="size-3.5" />}
            {!isRunning && !isSuccess && !isFailed && <Wrench className="size-3.5" />}
          </div>
          <span className="font-mono text-xs font-semibold tracking-tight text-foreground truncate">
            {tool.name}
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className={cn(
            "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium",
            isRunning && "bg-amber-500/15 text-amber-600 dark:text-amber-400",
            isSuccess && "bg-success/15 text-success",
            isFailed && "bg-destructive/15 text-destructive",
          )}>
            {isRunning ? "Running" : isSuccess ? "Success" : "Failed"}
          </span>

          <button
            type="button"
            onClick={() => setIsOpen(!isOpen)}
            className="flex size-6 items-center justify-center rounded-md hover:bg-muted text-muted-foreground transition-colors"
            aria-label="Toggle tool details"
          >
            {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
        </div>
      </div>

      {isOpen && (
        <div className="border-t bg-muted/30 px-3 py-2.5 space-y-2 text-xs">
          <div>
            <div className="text-[11px] font-medium text-muted-foreground mb-1 uppercase tracking-wider flex items-center gap-1">
              <Terminal className="size-3" /> Arguments
            </div>
            <pre className="overflow-x-auto rounded-lg bg-background p-2 font-mono text-[11px] text-foreground border">
              {tool.args || "{}"}
            </pre>
          </div>

          {tool.result !== undefined && (
            <div>
              <div className="text-[11px] font-medium text-muted-foreground mb-1 uppercase tracking-wider">
                Result
              </div>
              <div className="rounded-lg bg-background border p-2 font-mono text-[11px] text-foreground max-h-48 overflow-y-auto whitespace-pre-wrap">
                {linkifyText(tool.result)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
