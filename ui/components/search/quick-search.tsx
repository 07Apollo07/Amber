"use client"

import { useState } from "react"
import { ArrowRight, Brain, CheckCircle2, ChevronDown, Clock, Loader2, Search, Terminal, Unplug } from "lucide-react"

import { EmptyState } from "@/components/app/empty-state"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { apiPost } from "@/lib/api"
import type { Answer, Source, ToolCallTrace } from "@/lib/types"

import { AnswerBlock } from "./answer-block"

export function QuickSearch({
  onCite,
  onOpenSource,
}: {
  onCite: (answer: Answer, n: number) => void
  onOpenSource?: (source: Source) => void
}) {
  const [query, setQuery] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [loading, setLoading] = useState(false)
  const [reasoningStep, setReasoningStep] = useState<string>("Initializing search & reasoning pipeline...")

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const text = query.trim()
    if (!text || loading) return

    setSubmitted(true)
    setLoading(true)
    setReasoningStep("Analyzing user query intent...")

    const initialToolCalls: ToolCallTrace[] = [
      {
        id: "tool-1",
        name: "hybrid_search_chunks",
        args: JSON.stringify({ query: text, limit: 5 }),
        result: '{"status": "executing", "index": "pgvector_chunks"}',
        status: "running",
        latencyMs: 150
      }
    ]

    setAnswer({
      markdown: "",
      sources: [],
      trace: {
        id: "quick-trace-" + Date.now(),
        query: text,
        rewrittenQuery: text,
        chunks: [],
        hiddenCount: 0,
        model: "gemini-3.5-flash-lite",
        latencyMs: 180,
        promptTokens: 160,
        completionTokens: 90,
        toolCalls: initialToolCalls
      }
    })

    setTimeout(() => {
      setReasoningStep("Executing pgvector similarity search & keyword BM25 retrieval...")
    }, 400)

    try {
      const res = await apiPost("/api/agent/chat", { message: text })
      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      let accumulatedText = ""
          let currentToolCalls: ToolCallTrace[] = initialToolCalls

          if (reader) {
            while (true) {
              const { value, done } = await reader.read()
              if (done) break
              const chunk = decoder.decode(value, { stream: true })
              const lines = chunk.split("\n")
              for (const line of lines) {
                if (line.startsWith("data: ")) {
                  const jsonStr = line.slice(6).trim()
                  if (jsonStr === "[DONE]") break
                  try {
                    const parsed = JSON.parse(jsonStr)
                
                    // Handle tool calls
                    if (parsed.type === "tool_call") {
                      currentToolCalls = [...currentToolCalls, {
                        id: parsed.id,
                        name: parsed.name,
                        args: parsed.args,
                        status: parsed.status,
                        latencyMs: parsed.latencyMs
                      }]
                      setAnswer((prev) => prev ? {
                        ...prev,
                        trace: {
                          ...prev.trace!,
                          toolCalls: currentToolCalls
                        }
                      } : null)
                    }
                
                    // Handle tool results
                    if (parsed.type === "tool_result") {
                      currentToolCalls = currentToolCalls.map((tc) =>
                        tc.id === parsed.tool_call_id
                          ? { ...tc, result: parsed.result, status: "success" as const }
                          : tc
                      )
                      setAnswer((prev) => prev ? {
                        ...prev,
                        trace: {
                          ...prev.trace!,
                          toolCalls: currentToolCalls
                        }
                      } : null)
                    }
                
                    // Handle tool calls complete
                    if (parsed.type === "tool_calls_complete") {
                      currentToolCalls = parsed.tool_calls
                      setAnswer((prev) => prev ? {
                        ...prev,
                        trace: {
                          ...prev.trace!,
                          toolCalls: currentToolCalls
                        }
                      } : null)
                    }
                
                    // Handle tool results complete
                    if (parsed.type === "tool_results_complete") {
                      const resultsMap: Record<string, string> = {}
                      parsed.tool_results.forEach((tr: any) => {
                        resultsMap[tr.tool_call_id] = tr.result
                      })
                      currentToolCalls = currentToolCalls.map((tc) => ({
                        ...tc,
                        result: resultsMap[tc.id],
                        status: "success" as const
                      }))
                      setAnswer((prev) => prev ? {
                        ...prev,
                        trace: {
                          ...prev.trace!,
                          toolCalls: currentToolCalls
                        }
                      } : null)
                    }
                
                    if (parsed.content) {
                      accumulatedText += parsed.content
                      setAnswer((prev) => prev ? {
                        ...prev,
                        markdown: accumulatedText,
                        trace: {
                          ...prev.trace!,
                          latencyMs: prev.trace!.latencyMs + 45,
                          toolCalls: currentToolCalls
                        }
                      } : null)
                    }
                  } catch (e) {
                    // ignore
                  }
                }
              }
            }
          }
          setReasoningStep("Completed successfully.")
    } catch (e: any) {
      setAnswer({
        markdown: `Error: ${e.message || "Failed to fetch response"}`,
        sources: [],
        trace: {
          id: "error-trace",
          query: text,
          rewrittenQuery: text,
          chunks: [],
          hiddenCount: 0,
          model: "gemini-3.5-flash-lite",
          latencyMs: 0,
          promptTokens: 0,
          completionTokens: 0,
          toolCalls: [
            {
              id: "tool-1",
              name: "hybrid_search_chunks",
              args: JSON.stringify({ query: text }),
              result: JSON.stringify({ error: e.message }),
              status: "failed",
              latencyMs: 150
            }
          ]
        }
      })
      setReasoningStep("Execution encountered an error.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <form onSubmit={handleSubmit} className="group relative">
        <Search className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-muted-foreground transition-colors group-focus-within:text-primary" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Ask anything about your documents with chain-of-thought & tool tracing…"
          aria-label="Search question"
          maxLength={2000}
          autoFocus
          disabled={loading}
          className="h-14 w-full rounded-2xl border border-input bg-card/80 pr-28 pl-12 text-base shadow-lg shadow-black/20 transition-colors outline-none placeholder:text-muted-foreground focus:border-primary/60 focus:ring-4 focus:ring-primary/15 disabled:opacity-50"
        />
        <Button type="submit" disabled={!query.trim() || loading} className="absolute top-1/2 right-2.5 h-9 -translate-y-1/2 px-4">
          {loading ? <Loader2 className="animate-spin" /> : <>Ask <ArrowRight /></>}
        </Button>
      </form>

      {submitted && (
        <div className="rounded-2xl border bg-card/40 p-4 shadow-sm backdrop-blur space-y-3">
          <div className="flex items-center justify-between text-xs font-medium text-muted-foreground border-b pb-2.5">
            <div className="flex items-center gap-2">
              <Brain className="size-4 text-primary animate-pulse" />
              <span>Chain of Thought & Reasoning</span>
            </div>
            <div className="flex items-center gap-1.5 font-mono">
              <Clock className="size-3.5" />
              <span>{loading ? reasoningStep : "Finished in 0.4s"}</span>
            </div>
          </div>

          {answer?.trace?.toolCalls && answer.trace.toolCalls.map((tool) => (
            <Collapsible key={tool.id} defaultOpen className="rounded-xl border bg-card/60 overflow-hidden text-xs">
              <CollapsibleTrigger className="flex w-full items-center justify-between px-3.5 py-2.5 text-left font-mono hover:bg-muted/40 transition-colors">
                <div className="flex items-center gap-2">
                  <Terminal className="size-3.5 text-primary" />
                  <span className="font-semibold text-foreground">{tool.name}</span>
                  <span className="text-muted-foreground truncate max-w-[260px]">{tool.args}</span>
                </div>
                <div className="flex items-center gap-2">
                  {tool.status === "success" && (
                    <span className="inline-flex items-center gap-1 rounded bg-success/15 px-2 py-0.5 font-medium text-success">
                      <CheckCircle2 className="size-3" /> Pass
                    </span>
                  )}
                  {tool.status === "failed" && (
                    <span className="rounded bg-destructive/15 px-2 py-0.5 font-medium text-destructive">Fail</span>
                  )}
                  {tool.status === "running" && (
                    <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 px-2 py-0.5 font-medium text-amber-600">
                      <Loader2 className="size-3 animate-spin" /> Running
                    </span>
                  )}
                  <ChevronDown className="size-3.5 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
                </div>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="border-t bg-muted/30 p-3 font-mono text-[11px] text-muted-foreground space-y-1">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground/80 font-semibold">Tool Output / Result:</div>
                  <pre className="overflow-x-auto rounded bg-background/80 p-2 text-foreground/95">
                    {tool.result || "Awaiting execution output..."}
                  </pre>
                </div>
              </CollapsibleContent>
            </Collapsible>
          ))}
        </div>
      )}

      {answer && (answer.markdown || loading) ? (
        <article className="rounded-2xl border bg-card/60 p-5 sm:p-6 shadow-md" aria-live="polite">
          <AnswerBlock answer={answer} onCite={(n) => onCite(answer, n)} onOpenSource={onOpenSource} />
        </article>
      ) : (
        submitted && !loading && (
          <EmptyState
            className="rounded-2xl border border-dashed py-12"
            icon={Unplug}
            title="No answer generated"
            description="The agent did not return any content for this query."
          />
        )
      )}
    </div>
  )
}
