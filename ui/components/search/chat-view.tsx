"use client"

import { useEffect, useRef, useState } from "react"
import { ArrowUp, MessageSquare, MessagesSquare, PanelLeft, Plus, Trash2, ChevronDown } from "lucide-react"

import { AmberMark } from "@/components/app/amber-logo"
import { EmptyState } from "@/components/app/empty-state"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { apiPost } from "@/lib/api"
import { demoAction } from "@/lib/demo"
import type { Answer, ChatMessage, Conversation, ToolCallTrace, TraceChunk, Source } from "@/lib/types"
import { cn } from "@/lib/utils"

import { AnswerBlock } from "./answer-block"

function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  conversations: Conversation[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}) {
  return (
    <div className="flex h-full flex-col gap-2">
      <Button variant="outline" className="justify-start" onClick={onNew}>
        <Plus /> New chat
      </Button>
      {conversations.length === 0 && <EmptyState icon={MessagesSquare} title="No conversations yet" className="py-8" />}
      <nav aria-label="Conversations" className="-mx-1 flex-1 overflow-y-auto px-1">
        <ul className="space-y-0.5">
          {conversations.map((c) => (
            <li key={c.id} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                aria-current={activeId === c.id ? "true" : undefined}
                className={cn(
                  "flex w-full flex-col rounded-lg px-3 py-2 pr-9 text-left transition-colors hover:bg-muted/60",
                  activeId === c.id && "bg-muted",
                )}
              >
                <span className="truncate text-sm">{c.title}</span>
                <span className="text-xs text-muted-foreground">{c.updatedAt}</span>
              </button>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Delete ${c.title}`}
                className="absolute top-1/2 right-2 -translate-y-1/2 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                onClick={(e) => {
                  e.stopPropagation()
                  onDelete(c.id)
                }}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  )
}

export function ChatView({
  onCite,
  onOpenSource,
}: {
  onCite: (answer: Answer, n: number) => void
  onOpenSource?: (source: Source) => void
}) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState("")
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [traceSheetOpen, setTraceSheetOpen] = useState(false)
  const [traceOpen, setTraceOpen] = useState(false)
  const [toolCalls, setToolCalls] = useState<ToolCallTrace[]>([])
  const [toolResults, setToolResults] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages])

  const fetchConversations = async () => {
    try {
      const res = await fetch("/api/agent/conversations")
      if (res.ok) {
        const data = await res.json()
        setConversations(data)
      }
    } catch (e) {
      console.error("Failed to load conversations", e)
    }
  }

  useEffect(() => {
    fetchConversations()
  }, [])

  useEffect(() => {
    if (!activeId) {
      setMessages([])
      return
    }
    async function loadThread() {
      try {
        const res = await fetch(`/api/agent/conversations/${activeId}`)
        if (res.ok) {
          const data = await res.json()
          const loaded: ChatMessage[] = (data.messages || []).map((m: any, idx: number) => {
            const isUser = m.role === "user" || m.role === "human"
            const content = m.content || ""
            if (isUser) {
              return { id: `msg-${idx}`, role: "user" as const, text: content }
            } else {
              return {
                id: `msg-${idx}`,
                role: "assistant" as const,
                answer: {
                  markdown: content,
                  sources: [],
                  trace: {
                    id: `trace-${idx}`,
                    query: "",
                    rewrittenQuery: "",
                    chunks: [],
                    hiddenCount: 0,
                    model: "gemini-3.5-flash-lite",
                    latencyMs: 0,
                    promptTokens: 0,
                    completionTokens: 0,
                  }
                }
              }
            }
          })
          setMessages(loaded)
        }
      } catch (e) {
        console.error("Failed to load thread messages", e)
      }
    }
    loadThread()
  }, [activeId])

  async function send() {
    const text = draft.trim()
    if (!text || loading) return

    const userMsgId = crypto.randomUUID()
    const assistantMsgId = crypto.randomUUID()

    setMessages((m) => [
      ...m,
      { id: userMsgId, role: "user", text },
      {
        id: assistantMsgId,
        role: "assistant",
        answer: {
          markdown: "",
          sources: [],
          trace: {
            id: "stream-trace",
            query: text,
            rewrittenQuery: text,
            chunks: [],
            hiddenCount: 0,
            model: "gemini-3.5-flash-lite",
            latencyMs: 0,
            promptTokens: 0,
            completionTokens: 0,
          }
        }
      }
    ])
    setDraft("")
    setLoading(true)
      setToolCalls([])
      setToolResults({})
      setTraceOpen(true)

      try {
        const res = await apiPost("/api/agent/chat", {
          message: text,
          thread_id: activeId,
        })

        const reader = res.body?.getReader()
        const decoder = new TextDecoder()
        let accumulatedText = ""

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
                  if (parsed.thread_id && !activeId) {
                    setActiveId(parsed.thread_id)
                  }
                
                  // Handle tool calls
                  if (parsed.type === "tool_call") {
                    setToolCalls((prev) => [...prev, {
                      id: parsed.id,
                      name: parsed.name,
                      args: parsed.args,
                      status: parsed.status,
                      latencyMs: parsed.latencyMs
                    }])
                  }
                
                  // Handle tool results
                  if (parsed.type === "tool_result") {
                    const toolCallId = parsed.tool_call_id
                    setToolResults((prev) => ({ ...prev, [toolCallId]: parsed.result }))
                    setToolCalls((prev) => prev.map((tc) => 
                      tc.id === toolCallId 
                        ? { ...tc, result: parsed.result, status: "success" as const }
                        : tc
                    ))
                  }
                
                  // Handle tool calls complete
                  if (parsed.type === "tool_calls_complete") {
                    setToolCalls(parsed.tool_calls)
                  }
                
                  // Handle tool results complete
                  if (parsed.type === "tool_results_complete") {
                    const resultsMap: Record<string, string> = {}
                    parsed.tool_results.forEach((tr: any) => {
                      resultsMap[tr.tool_call_id] = tr.result
                    })
                    setToolResults(resultsMap)
                    setToolCalls((prev) => prev.map((tc) => ({
                      ...tc,
                      result: resultsMap[tc.id],
                      status: "success" as const
                    })))
                  }
                
                  if (parsed.content) {
                    accumulatedText += parsed.content
                    setMessages((m) => {
                      const copy = [...m]
                      const last = copy[copy.length - 1]
                      if (last && last.role === "assistant") {
                        copy[copy.length - 1] = {
                          ...last,
                          answer: {
                            ...last.answer!,
                            markdown: accumulatedText,
                          }
                        }
                      }
                      return copy
                    })
                  }
                  if (parsed.error) {
                    accumulatedText += `\n[Error: ${parsed.error}]`
                    setMessages((m) => {
                      const copy = [...m]
                      const last = copy[copy.length - 1]
                      if (last && last.role === "assistant") {
                        copy[copy.length - 1] = {
                          ...last,
                          answer: {
                            ...last.answer!,
                            markdown: accumulatedText,
                          }
                        }
                      }
                      return copy
                    })
                  }
                } catch (e) {
                  // ignore
                }
              }
            }
          }
        }
        fetchConversations()
      } catch (e: any) {
        demoAction("Failed to send message", e.message)
      } finally {
        setLoading(false)
      }
    }

  function newChat() {
    setActiveId(null)
    setMessages([])
    setDrawerOpen(false)
  }

  function select(id: string) {
    setActiveId(id)
    setDrawerOpen(false)
  }

  function removeConversation(id: string) {
    if (activeId === id) {
      newChat()
    }
    setConversations((c) => c.filter((item) => item.id !== id))
    demoAction("Conversation deleted")
  }

  return (
    <div className="flex h-[calc(100dvh-14rem)] min-h-[520px] gap-4">
      <aside className="hidden w-64 shrink-0 lg:block">
        <ConversationList
          conversations={conversations}
          activeId={activeId}
          onSelect={select}
          onNew={newChat}
          onDelete={removeConversation}
        />
      </aside>

      <section className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-card/40">
              {/* Chat header with trace button (desktop) */}
              <div className="hidden lg:flex items-center justify-between border-b px-3 py-2">
                <div className="flex items-center gap-2">
                  <AmberMark className="size-5" />
                  <span className="font-medium">Chat</span>
                </div>
                {(toolCalls.length > 0 || traceOpen) && (
                  <Button variant="ghost" size="icon" onClick={() => setTraceOpen(!traceOpen)} className="gap-1">
                    <ChevronDown className={cn("size-4 transition-transform", traceOpen && "rotate-180")} />
                    <span className="text-xs">Trace</span>
                  </Button>
                )}
              </div>
        
              {/* Tool Calls Trace Panel - right sidebar (desktop) */}
          <div className="hidden lg:block w-72 border-l bg-muted/20" style={{ display: (toolCalls.length > 0 || traceOpen) ? 'flex' : 'none' }}>
            <div className="p-3 border-b flex items-center justify-between">
              <h3 className="font-medium text-sm">Trace</h3>
              <Button variant="ghost" size="icon-xs" onClick={() => setTraceOpen(!traceOpen)}>
                <ChevronDown className={cn("size-4 transition-transform", traceOpen && "rotate-180")} />
              </Button>
            </div>
            {traceOpen && (
                          <div className="p-3 max-h-[calc(100%-50px)] overflow-y-auto space-y-3">
                {toolCalls.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Tool Executions</div>
                    {toolCalls.map((tool) => (
                      <div key={tool.id} className="space-y-1 rounded-lg border bg-card/60 p-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-mono font-medium text-foreground">{tool.name}</span>
                          <div className="flex items-center gap-1">
                            {tool.status === "success" && (
                              <span className="rounded bg-success/15 px-1.5 py-0.5 font-medium text-success">Pass</span>
                            )}
                            {tool.status === "failed" && (
                              <span className="rounded bg-destructive/15 px-1.5 py-0.5 font-medium text-destructive">Fail</span>
                            )}
                            {tool.status === "running" && (
                              <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-medium text-amber-600">Running</span>
                            )}
                          </div>
                        </div>
                        <div className="mt-1 text-muted-foreground font-mono text-[11px] truncate">{tool.args}</div>
                        {tool.result && (
                          <Collapsible defaultOpen={false}>
                            <CollapsibleTrigger className="mt-1 text-xs text-primary hover:underline cursor-pointer">
                              Show result
                            </CollapsibleTrigger>
                            <CollapsibleContent className="mt-1">
                              <pre className="bg-muted p-2 rounded text-[10px] overflow-x-auto max-h-40">{tool.result}</pre>
                            </CollapsibleContent>
                          </Collapsible>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        <div className="flex items-center gap-2 border-b px-3 py-2 lg:hidden">
          <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="sm">
                <PanelLeft /> Conversations
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-4">
              <SheetHeader className="p-0">
                <SheetTitle>Conversations</SheetTitle>
              </SheetHeader>
              <ConversationList
                conversations={conversations}
                activeId={activeId}
                onSelect={select}
                onNew={newChat}
                onDelete={removeConversation}
              />
            </SheetContent>
          </Sheet>
                  {(toolCalls.length > 0 || traceOpen) && (
                    <Sheet open={traceSheetOpen} onOpenChange={setTraceSheetOpen}>
                      <SheetTrigger asChild>
                        <Button variant="ghost" size="sm" className="gap-1">
                          <ChevronDown className="size-4" />
                          Trace
                        </Button>
                      </SheetTrigger>
                      <SheetContent side="right" className="w-72 p-4">
                        <SheetHeader className="p-0">
                          <SheetTitle>Trace</SheetTitle>
                        </SheetHeader>
                                                <div className="space-y-3 max-h-[60vh] overflow-y-auto">
                          {toolCalls.length > 0 && (
                            <div className="space-y-2">
                              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Tool Executions</div>
                              {toolCalls.map((tool) => (
                                <div key={tool.id} className="space-y-1 rounded-lg border bg-card/60 p-2 text-xs">
                                  <div className="flex items-center justify-between">
                                    <span className="font-mono font-medium text-foreground">{tool.name}</span>
                                    <div className="flex items-center gap-1">
                                      {tool.status === "success" && (
                                        <span className="rounded bg-success/15 px-1.5 py-0.5 font-medium text-success">Pass</span>
                                      )}
                                      {tool.status === "failed" && (
                                        <span className="rounded bg-destructive/15 px-1.5 py-0.5 font-medium text-destructive">Fail</span>
                                      )}
                                      {tool.status === "running" && (
                                        <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-medium text-amber-600">Running</span>
                                      )}
                                    </div>
                                  </div>
                                  <div className="mt-1 text-muted-foreground font-mono text-[11px] truncate">{tool.args}</div>
                                  {tool.result && (
                                    <Collapsible defaultOpen={false}>
                                      <CollapsibleTrigger className="mt-1 text-xs text-primary hover:underline cursor-pointer">
                                        Show result
                                      </CollapsibleTrigger>
                                      <CollapsibleContent className="mt-1">
                                        <pre className="bg-muted p-2 rounded text-[10px] overflow-x-auto max-h-40">{tool.result}</pre>
                                      </CollapsibleContent>
                                    </Collapsible>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </SheetContent>
                    </Sheet>
                  )}
                </div>

        <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center text-muted-foreground">
              <MessageSquare className="mb-3 size-8 text-primary/70" />
              <p className="font-medium text-foreground">Start a conversation</p>
              <p className="mt-1 max-w-sm text-sm">Ask a question. Follow-ups keep the context of earlier messages.</p>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-8">
              {messages.map((message) =>
                message.role === "user" ? (
                  <div key={message.id} className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary/12 px-4 py-2.5 text-[15px] whitespace-pre-wrap">
                      {message.text}
                    </div>
                  </div>
                ) : (
                  <div key={message.id} className="flex gap-3">
                    <AmberMark className="mt-1 size-6 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <AnswerBlock answer={message.answer!} onCite={(n) => onCite(message.answer!, n)} onOpenSource={onOpenSource} />
                    </div>
                  </div>
                ),
              )}
              <div ref={endRef} />
            </div>
          )}
        </div>

        <form
          className="border-t p-3"
          onSubmit={(event) => {
            event.preventDefault()
            send()
          }}
        >
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-input bg-background/60 p-2 focus-within:border-primary/60 focus-within:ring-4 focus-within:ring-primary/15">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault()
                  send()
                }
              }}
              rows={1}
              maxLength={2000}
              placeholder="Ask a follow-up…"
              aria-label="Message"
              disabled={loading}
              className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-muted-foreground"
            />
            <Button type="submit" size="icon" aria-label="Send" disabled={!draft.trim() || loading}>
              <ArrowUp />
            </Button>
          </div>
          <p className="mt-1.5 text-center text-[11px] text-muted-foreground">Enter to send · Shift + Enter for a new line</p>
        </form>
      </section>
    </div>
  )
}
