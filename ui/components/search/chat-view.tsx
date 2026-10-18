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
import { ToolElement } from "./tool-element"

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
          const rawMessages = data.messages || []
          const loaded: ChatMessage[] = []
          
          let currentToolCalls: ToolCallTrace[] = []
          let pendingAssistantMarkdown = ""

          for (let idx = 0; idx < rawMessages.length; idx++) {
            const m = rawMessages[idx]
            const role = m.role || m.type || ""
            const isUser = role === "user" || role === "human"
            const content = m.content || m.kwargs?.content || ""

            if (isUser) {
              // Flush any accumulated assistant turn before starting a user turn
              if (pendingAssistantMarkdown || currentToolCalls.length > 0) {
                loaded.push({
                  id: `msg-asst-${idx}`,
                  role: "assistant",
                  answer: {
                    markdown: pendingAssistantMarkdown,
                    sources: [],
                    toolCalls: [...currentToolCalls],
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
                })
                pendingAssistantMarkdown = ""
                currentToolCalls = []
              }
              loaded.push({ id: `msg-user-${idx}`, role: "user", text: content })
            } else {
              // Assistant / AI / Tool message
              const toolCallsList = m.tool_calls || m.kwargs?.tool_calls
              const toolCallId = m.tool_call_id || m.kwargs?.tool_call_id
              const isToolResult = role.includes("tool") || role === "ToolMessage" || toolCallId

              if (toolCallsList && Array.isArray(toolCallsList)) {
                for (const tc of toolCallsList) {
                  const tcId = tc.id || tc.args?.id || crypto.randomUUID()
                  const tcName = tc.name || tc.type || "unknown_tool"
                  const tcArgs = tc.args ? (typeof tc.args === "string" ? tc.args : JSON.stringify(tc.args, null, 2)) : "{}"
                  currentToolCalls.push({
                    id: tcId,
                    name: tcName,
                    args: tcArgs,
                    status: "running"
                  })
                }
              }

              if (isToolResult) {
                const matchingId = toolCallId || (toolCallsList && toolCallsList[0]?.id)
                const targetTc = matchingId 
                  ? currentToolCalls.find(t => t.id === matchingId)
                  : currentToolCalls.find(t => t.status === "running")
                
                if (targetTc) {
                  targetTc.result = content
                  targetTc.status = "success"
                } else if (currentToolCalls.length > 0) {
                  currentToolCalls[currentToolCalls.length - 1].result = content
                  currentToolCalls[currentToolCalls.length - 1].status = "success"
                }
              }

              if (content && !isToolResult && !role.includes("tool")) {
                pendingAssistantMarkdown = content
              }
            }
          }

          if (pendingAssistantMarkdown || currentToolCalls.length > 0) {
            loaded.push({
              id: `msg-asst-final`,
              role: "assistant",
              answer: {
                markdown: pendingAssistantMarkdown,
                sources: [],
                toolCalls: [...currentToolCalls],
                trace: {
                  id: `trace-final`,
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
            })
          }

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

    const processMessages = (msgs: any[]) => {
      if (!Array.isArray(msgs)) return
      for (const msg of msgs) {
        if (!msg) continue
        const msgType = msg.type || msg.role || msg.id || ""
        const toolCallsList = msg.tool_calls || msg.kwargs?.tool_calls
        const toolCallId = msg.tool_call_id || msg.kwargs?.tool_call_id
        const toolName = msg.name || msg.kwargs?.name

        // 1. Tool calls in AI messages
        if (toolCallsList && Array.isArray(toolCallsList)) {
          for (const tc of toolCallsList) {
            const tcId = tc.id || tc.args?.id || crypto.randomUUID()
            const tcName = tc.name || tc.type || "unknown_tool"
            const tcArgs = tc.args ? (typeof tc.args === "string" ? tc.args : JSON.stringify(tc.args, null, 2)) : "{}"

            setToolCalls((prev) => {
              const exists = prev.find((t) => t.id === tcId)
              if (exists) {
                return prev.map((t) => (t.id === tcId ? { ...t, args: tcArgs, name: tcName } : t))
              }
              return [...prev, { id: tcId, name: tcName, args: tcArgs, status: "running" }]
            })

            // Immediately update assistant message toolCalls inline
            setMessages((m) => {
              const copy = [...m]
              const last = copy[copy.length - 1]
              if (last && last.role === "assistant") {
                const existingTools = last.answer?.toolCalls || []
                const found = existingTools.find(t => t.id === tcId)
                const updatedTools = found
                  ? existingTools.map(t => t.id === tcId ? { ...t, args: tcArgs, name: tcName } : t)
                  : [...existingTools, { id: tcId, name: tcName, args: tcArgs, status: "running" as const }]
                copy[copy.length - 1] = {
                  ...last,
                  answer: {
                    ...last.answer!,
                    toolCalls: updatedTools,
                  }
                }
              }
              return copy
            })
          }
        }

        // 2. Tool results
        if (msgType.includes("tool") || msgType === "ToolMessage" || toolCallId) {
          const resultText = msg.content || msg.kwargs?.content || ""
          const matchingId = toolCallId || (toolCallsList && toolCallsList[0]?.id)

          if (matchingId) {
            setToolCalls((prev) =>
              prev.map((t) => (t.id === matchingId ? { ...t, result: resultText, status: "success" } : t))
            )
            setMessages((m) => {
              const copy = [...m]
              const last = copy[copy.length - 1]
              if (last && last.role === "assistant" && last.answer?.toolCalls) {
                copy[copy.length - 1] = {
                  ...last,
                  answer: {
                    ...last.answer!,
                    toolCalls: last.answer.toolCalls.map(t => t.id === matchingId ? { ...t, result: resultText, status: "success" as const } : t)
                  }
                }
              }
              return copy
            })
          } else if (toolName) {
            setToolCalls((prev) => {
              const lastRunning = [...prev].reverse().find((t) => t.name === toolName && t.status === "running")
              if (lastRunning) {
                return prev.map((t) => (t.id === lastRunning.id ? { ...t, result: resultText, status: "success" } : t))
              }
              return prev
            })
            setMessages((m) => {
              const copy = [...m]
              const last = copy[copy.length - 1]
              if (last && last.role === "assistant" && last.answer?.toolCalls) {
                const lastRunning = [...last.answer.toolCalls].reverse().find(t => t.name === toolName && t.status === "running")
                if (lastRunning) {
                  copy[copy.length - 1] = {
                    ...last,
                    answer: {
                      ...last.answer!,
                      toolCalls: last.answer.toolCalls.map(t => t.id === lastRunning.id ? { ...t, result: resultText, status: "success" as const } : t)
                    }
                  }
                }
              }
              return copy
            })
          }
        }
      }
    }

      try {
        const res = await apiPost("/api/agent/v2/stream", {
          message: text,
          thread_id: activeId,
        })

        const reader = res.body?.getReader()
        const decoder = new TextDecoder()
        let accumulatedText = ""
        let currentEvent = ""

        if (reader) {
          let buffer = ""
          while (true) {
            const { value, done } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split("\n")
            buffer = lines.pop() || ""

            for (const line of lines) {
              if (line.startsWith("event: ")) {
                currentEvent = line.slice(7).trim()
              } else if (line.startsWith("data: ")) {
                const jsonStr = line.slice(6).trim()
                if (jsonStr === "[DONE]") break
                try {
                  const parsed = JSON.parse(jsonStr)

                  if (currentEvent.startsWith("metadata") && parsed.thread_id && !activeId) {
                    setActiveId(parsed.thread_id)
                  }

                  // Handle custom tool events
                  if (currentEvent === "tool_call" || parsed.type === "tool_call") {
                    const tc = parsed
                    const tcId = tc.id || tc.tool_call_id || crypto.randomUUID()
                    setToolCalls((prev) => {
                      const exists = prev.find((t) => t.id === tcId)
                      if (exists) return prev
                      return [...prev, { id: tcId, name: tc.name, args: tc.args || "{}", status: tc.status || "running" }]
                    })
                  }
                  if (currentEvent === "tool_result" || parsed.type === "tool_result") {
                    const tr = parsed
                    const trId = tr.tool_call_id || tr.id
                    setToolCalls((prev) =>
                      prev.map((t) => (t.id === trId || t.name === tr.name ? { ...t, result: tr.result, status: "success" } : t))
                    )
                  }

                  // Handle LangGraph v2 "messages" stream mode
                  if (currentEvent.includes("messages") && Array.isArray(parsed) && parsed.length > 0) {
                    processMessages([parsed[0]])
                    const msg = parsed[0]
                    const content = msg?.content || msg?.kwargs?.content
                    const msgType = msg?.type || msg?.id || ""
                    if (content && typeof content === "string" && (typeof msgType === "string" && (msgType.includes("AI") || msgType === "ai" || msgType === "AIMessageChunk"))) {
                      accumulatedText += content
                      setMessages((m) => {
                        const copy = [...m]
                        const last = copy[copy.length - 1]
                        if (last && last.role === "assistant") {
                          copy[copy.length - 1] = {
                            ...last,
                            answer: {
                              ...last.answer!,
                              markdown: accumulatedText,
                              toolCalls: toolCalls.length > 0 ? [...toolCalls] : last.answer?.toolCalls,
                            }
                          }
                        }
                        return copy
                      })
                    }
                  }

                  // Handle LangGraph v2 "values" or "updates" stream modes
                  if (currentEvent.includes("values") || currentEvent.includes("updates")) {
                    const rawMessages = parsed?.messages || (parsed?.agent && parsed.agent.messages) || (parsed?.tools && parsed.tools.messages)
                    if (Array.isArray(rawMessages) && rawMessages.length > 0) {
                      processMessages(rawMessages)
                      const lastMsg = rawMessages[rawMessages.length - 1]
                      const content = lastMsg?.content || lastMsg?.kwargs?.content
                      const msgType = lastMsg?.type || lastMsg?.role || ""
                      if (content && typeof content === "string" && (msgType.includes("AI") || msgType === "ai" || msgType === "AIMessage" || msgType === "assistant")) {
                        accumulatedText = content
                        setMessages((m) => {
                          const copy = [...m]
                          const last = copy[copy.length - 1]
                          if (last && last.role === "assistant") {
                            copy[copy.length - 1] = {
                              ...last,
                              answer: {
                                ...last.answer!,
                                markdown: accumulatedText,
                                toolCalls: toolCalls.length > 0 ? [...toolCalls] : last.answer?.toolCalls,
                              }
                            }
                          }
                          return copy
                        })
                      }
                    }
                  }

                  if (currentEvent.includes("error") && parsed.error) {
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
                  // ignore JSON parse errors on intermediate text chunks
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
        <div className="flex items-center gap-2 border-b px-3 py-2">
          <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="sm" className="lg:hidden">
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
          <div className="flex items-center gap-2">
            <AmberMark className="size-5" />
            <span className="font-medium">Chat</span>
          </div>
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
