"use client"

import { useEffect, useRef, useState } from "react"
import { MessageSquare, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react"

import { AmberMark } from "@/components/app/amber-logo"
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation"
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message"
import {
  PromptInput,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input"
import { Shimmer } from "@/components/ai-elements/shimmer"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { apiDelete, apiPost, apiPut } from "@/lib/api"
import { demoAction } from "@/lib/demo"
import type { Conversation as ConversationRecord } from "@/lib/types"
import { cn } from "@/lib/utils"

import { ToolElement } from "./tool-element"

type TextEntry = {
  id: string
  kind: "text"
  role: "user" | "assistant"
  text: string
}

type ToolEntry = {
  id: string
  kind: "tool"
  callId: string
  name: string
  args: string
  result?: string
  status: "running" | "success" | "failed"
}

type TimelineEntry = TextEntry | ToolEntry

type AgentToolCall = {
  id?: string
  name?: string
  args?: unknown
}

type AgentMessage = {
  id?: string
  type?: string
  role?: string
  content?: unknown
  tool_calls?: AgentToolCall[]
  tool_call_id?: string
  name?: string
  status?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function getMessageText(content: unknown): string {
  if (typeof content === "string") return content
  if (!Array.isArray(content)) return ""

  return content
    .map((part) => {
      if (typeof part === "string") return part
      if (isRecord(part) && typeof part.text === "string") return part.text
      return ""
    })
    .join("")
}

function formatToolArgs(args: unknown): string {
  if (typeof args === "string") return args
  if (args === undefined || args === null) return "{}"
  return JSON.stringify(args, null, 2)
}

function getMessagesFromUpdate(data: unknown): AgentMessage[] {
  if (!isRecord(data)) return []
  if (Array.isArray(data.messages)) return data.messages as AgentMessage[]

  return Object.values(data).flatMap((nodeUpdate) => {
    if (!isRecord(nodeUpdate) || !Array.isArray(nodeUpdate.messages)) return []
    return nodeUpdate.messages as AgentMessage[]
  })
}

function isAssistantMessage(message: AgentMessage): boolean {
  const role = message.type || message.role || ""
  return role === "ai" || role === "assistant" || role === "AIMessage" || role === "AIMessageChunk"
}

function isToolMessage(message: AgentMessage): boolean {
  const role = message.type || message.role || ""
  return role === "tool" || role === "ToolMessage" || Boolean(message.tool_call_id)
}

function makeHistory(messages: AgentMessage[]): TimelineEntry[] {
  const entries: TimelineEntry[] = []

  for (const [messageIndex, message] of messages.entries()) {
    const role = message.type || message.role || ""
    const text = getMessageText(message.content)

    if (role === "human" || role === "user") {
      entries.push({
        id: message.id || `user-${messageIndex}`,
        kind: "text",
        role: "user",
        text,
      })
      continue
    }

    if (isAssistantMessage(message)) {
      if (text) {
        entries.push({
          id: message.id || `assistant-${messageIndex}`,
          kind: "text",
          role: "assistant",
          text,
        })
      }

      for (const [callIndex, call] of (message.tool_calls || []).entries()) {
        const callId = call.id || `${message.id || messageIndex}-${callIndex}`
        entries.push({
          id: `tool-${callId}`,
          kind: "tool",
          callId,
          name: call.name || "Tool",
          args: formatToolArgs(call.args),
          status: "running",
        })
      }
      continue
    }

    if (isToolMessage(message)) {
      const callId = message.tool_call_id || `tool-result-${messageIndex}`
      const existing = entries.find(
        (entry): entry is ToolEntry => entry.kind === "tool" && entry.callId === callId,
      )
      const result = text || formatToolArgs(message.content)

      if (existing) {
        existing.result = result
        existing.status = message.status === "error" ? "failed" : "success"
      } else {
        entries.push({
          id: `tool-${callId}`,
          kind: "tool",
          callId,
          name: message.name || "Tool",
          args: "{}",
          result,
          status: message.status === "error" ? "failed" : "success",
        })
      }
    }
  }

  return entries
}

export function ChatLayout() {
  const [conversations, setConversations] = useState<ConversationRecord[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [entries, setEntries] = useState<TimelineEntry[]>([])
  const [draft, setDraft] = useState("")
  const [loading, setLoading] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState("")
  const [savingConversationId, setSavingConversationId] = useState<string | null>(null)
  const skipNextLoadRef = useRef<string | null>(null)

  async function fetchConversations(): Promise<ConversationRecord[]> {
    const response = await fetch("/api/agent/conversations")
    if (!response.ok) {
      throw new Error(`Failed to load conversations (${response.status})`)
    }
    return response.json()
  }

  useEffect(() => {
    fetchConversations()
      .then(setConversations)
      .catch((error: unknown) => console.error("Failed to load conversations", error))
  }, [])

  useEffect(() => {
    if (!activeId) return
    if (skipNextLoadRef.current === activeId) {
      skipNextLoadRef.current = null
      return
    }

    const controller = new AbortController()
    async function loadThread() {
      try {
        const response = await fetch(`/api/agent/conversations/${activeId}`, {
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error(`Failed to load conversation (${response.status})`)
        }
        const data: { messages?: AgentMessage[]; error?: string } = await response.json()
        if (data.error) throw new Error(data.error)
        setEntries(makeHistory(data.messages || []))
      } catch (error) {
        if (!controller.signal.aborted) {
          console.error("Failed to load conversation", error)
          demoAction(
            "Failed to load conversation",
            error instanceof Error ? error.message : String(error),
          )
        }
      }
    }

    void loadThread()
    return () => controller.abort()
  }, [activeId])

  function addOrUpdateTool(call: AgentToolCall, index: number, messageId?: string) {
    const callId = call.id || `${messageId || "tool"}-${index}`
    const id = `tool-${callId}`
    setEntries((current) => {
      const existingIndex = current.findIndex(
        (entry) => entry.kind === "tool" && entry.callId === callId,
      )
      const toolEntry: ToolEntry = {
        id,
        kind: "tool",
        callId,
        name: call.name || "Tool",
        args: formatToolArgs(call.args),
        status: "running",
      }

      if (existingIndex < 0) return [...current, toolEntry]
      return current.map((entry, entryIndex) =>
        entryIndex === existingIndex && entry.kind === "tool"
          ? { ...entry, ...toolEntry, result: entry.result, status: entry.status }
          : entry,
      )
    })
  }

  function addOrUpdateToolResult(message: AgentMessage) {
    const callId = message.tool_call_id
    if (!callId) return
    const result = getMessageText(message.content) || formatToolArgs(message.content)
    setEntries((current) => {
      const existingIndex = current.findIndex(
        (entry) => entry.kind === "tool" && entry.callId === callId,
      )
      if (existingIndex < 0) {
        return [
          ...current,
          {
            id: `tool-${callId}`,
            kind: "tool",
            callId,
            name: message.name || "Tool",
            args: "{}",
            result,
            status: message.status === "error" ? "failed" : "success",
          },
        ]
      }
      return current.map((entry, index) =>
        index === existingIndex && entry.kind === "tool"
          ? {
              ...entry,
              result,
              status: message.status === "error" ? "failed" : "success",
            }
          : entry,
      )
    })
  }

  async function send(text: string) {
    const trimmedText = text.trim()
    if (!trimmedText || loading) return

    const shouldGenerateTitle = activeId === null
    setEntries((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        kind: "text",
        role: "user",
        text: trimmedText,
      },
    ])
    setDraft("")
    setLoading(true)

    let threadId = activeId
    const textEntryIds = new Map<string, string>()
    const fallbackTextId = crypto.randomUUID()

    function appendAssistantText(message: AgentMessage, content: string) {
      const messageId = message.id || "assistant"
      const entryId = textEntryIds.get(messageId) || fallbackTextId
      textEntryIds.set(messageId, entryId)

      setEntries((current) => {
        const existing = current.find(
          (entry): entry is TextEntry => entry.kind === "text" && entry.id === entryId,
        )
        if (existing) {
          return current.map((entry) =>
            entry.kind === "text" && entry.id === entryId
              ? { ...entry, text: entry.text + content }
              : entry,
          )
        }
        return [
          ...current,
          { id: entryId, kind: "text", role: "assistant", text: content },
        ]
      })
    }

    try {
      const response = await apiPost("/api/agent/v2/stream", {
        message: trimmedText,
        thread_id: threadId,
      })
      if (!response.body) throw new Error("The chat stream did not include a response body.")

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let eventName = ""
      let streamEnded = false

      while (!streamEnded) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventName = line.slice(7).trim()
            continue
          }
          if (!line.startsWith("data: ")) continue

          const rawData = line.slice(6).trim()
          if (rawData === "[DONE]") {
            streamEnded = true
            break
          }

          let data: unknown
          try {
            data = JSON.parse(rawData)
          } catch (error) {
            throw new Error(
              `Could not read ${eventName || "chat"} stream data: ${
                error instanceof Error ? error.message : String(error)
              }`,
            )
          }

          if (eventName === "metadata" && isRecord(data) && typeof data.thread_id === "string") {
            threadId = data.thread_id
            skipNextLoadRef.current = threadId === activeId ? null : threadId
            setActiveId(threadId)
            continue
          }

          if (eventName === "error") {
            const detail = isRecord(data) && typeof data.error === "string"
              ? data.error
              : "The agent stream failed."
            throw new Error(detail)
          }

          if (eventName.startsWith("messages") && Array.isArray(data) && isRecord(data[0])) {
            const message = data[0] as AgentMessage
            if (isAssistantMessage(message)) {
              const content = getMessageText(message.content)
              if (content) appendAssistantText(message, content)
              for (const [index, call] of (message.tool_calls || []).entries()) {
                addOrUpdateTool(call, index, message.id)
              }
            } else if (isToolMessage(message)) {
              addOrUpdateToolResult(message)
            }
            continue
          }

          if (eventName.startsWith("updates")) {
            for (const message of getMessagesFromUpdate(data)) {
              if (isAssistantMessage(message)) {
                for (const [index, call] of (message.tool_calls || []).entries()) {
                  addOrUpdateTool(call, index, message.id)
                }
              } else if (isToolMessage(message)) {
                addOrUpdateToolResult(message)
              }
            }
          }
        }
      }

      await reader.cancel()
      if (shouldGenerateTitle && threadId) {
        try {
          const titleResponse = await apiPost(
            `/api/agent/conversations/${threadId}/generate-title`,
          )
          const titledConversation: { title: string } = await titleResponse.json()
          setConversations((current) =>
            current.map((conversation) =>
              conversation.id === threadId
                ? { ...conversation, title: titledConversation.title }
                : conversation,
            ),
          )
        } catch (error) {
          console.error("Failed to generate conversation title", error)
        }
      }

      fetchConversations()
        .then(setConversations)
        .catch((error: unknown) => console.error("Failed to refresh conversations", error))
    } catch (error) {
      demoAction(
        "Failed to send message",
        error instanceof Error ? error.message : String(error),
      )
    } finally {
      setLoading(false)
    }
  }

  function newChat() {
    skipNextLoadRef.current = null
    setActiveId(null)
    setEntries([])
  }

  function selectConversation(id: string) {
    if (id === activeId) return
    skipNextLoadRef.current = null
    setEntries([])
    setActiveId(id)
  }

  function beginRename(conversation: ConversationRecord) {
    setEditingId(conversation.id)
    setEditingTitle(conversation.title)
  }

  async function saveRename(conversationId: string) {
    const title = editingTitle.trim()
    if (!title || savingConversationId) return

    setSavingConversationId(conversationId)
    try {
      const response = await apiPut(`/api/agent/conversations/${conversationId}`, { name: title })
      const updated: { title: string } = await response.json()
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === conversationId
            ? { ...conversation, title: updated.title }
            : conversation,
        ),
      )
      setEditingId(null)
      setEditingTitle("")
    } catch (error) {
      demoAction(
        "Failed to rename conversation",
        error instanceof Error ? error.message : String(error),
      )
    } finally {
      setSavingConversationId(null)
    }
  }

  async function deleteConversation(conversation: ConversationRecord) {
    if (!window.confirm(`Delete “${conversation.title}”? This cannot be undone.`)) return

    setSavingConversationId(conversation.id)
    try {
      await apiDelete(`/api/agent/conversations/${conversation.id}`)
      setConversations((current) =>
        current.filter((item) => item.id !== conversation.id),
      )
      if (activeId === conversation.id) newChat()
    } catch (error) {
      demoAction(
        "Failed to delete conversation",
        error instanceof Error ? error.message : String(error),
      )
    } finally {
      setSavingConversationId(null)
    }
  }

  return (
    <div className="grid h-[calc(100dvh-7.5rem)] min-h-[520px] w-full grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,4fr)]">
      <aside className="hidden min-w-0 flex-col overflow-hidden rounded-2xl border bg-card/70 p-3 lg:flex">
        <div className="mb-2 flex items-center justify-between border-b px-1 pb-3">
          <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <MessageSquare className="size-3.5" />
            Conversations
          </span>
          <Button variant="ghost" size="icon-xs" onClick={newChat} aria-label="New chat">
            <Plus className="size-3.5" />
          </Button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto pr-1">
          {conversations.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">
              Your conversations will appear here.
            </p>
          ) : (
            conversations.map((conversation) => (
              <div
                key={conversation.id}
                className="group flex items-start gap-1 rounded-lg pr-1 transition-colors hover:bg-muted/80"
              >
                <button
                  type="button"
                  onClick={() => selectConversation(conversation.id)}
                  className={cn(
                    "min-w-0 flex-1 px-2.5 py-2 text-left text-xs",
                    activeId === conversation.id && "font-medium text-primary",
                  )}
                >
                  <span className="block truncate">{conversation.title}</span>
                  <span className="mt-1 block text-[10px] text-muted-foreground">
                    {conversation.updatedAt}
                  </span>
                </button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      className="mt-1 shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                      aria-label={`Actions for ${conversation.title}`}
                      disabled={savingConversationId === conversation.id}
                    >
                      <MoreHorizontal className="size-3.5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-40">
                    <DropdownMenuItem onSelect={() => beginRename(conversation)}>
                      <Pencil />
                      Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      variant="destructive"
                      onSelect={() => void deleteConversation(conversation)}
                    >
                      <Trash2 />
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ))
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-card/40">
        <header className="flex items-center justify-between gap-3 border-b bg-muted/20 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10">
              <AmberMark className="size-5" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold">Amber Assistant</h1>
              <p className="truncate text-xs text-muted-foreground">
                Chat with your documents and tools
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={newChat} className="shrink-0">
            <Plus className="size-4" />
            New chat
          </Button>
        </header>

        {conversations.length > 0 && (
          <nav
            aria-label="Recent conversations"
            className="flex gap-2 overflow-x-auto border-b px-3 py-2 lg:hidden"
          >
            {conversations.map((conversation) => (
              <div
                key={conversation.id}
              >
                <div
                  className={cn(
                    "flex max-w-56 shrink-0 items-center rounded-full border text-xs text-muted-foreground transition-colors hover:bg-muted",
                    activeId === conversation.id && "border-primary/50 bg-primary/10 text-foreground",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => selectConversation(conversation.id)}
                    className="min-w-0 truncate py-1.5 pl-3 pr-1 text-left"
                  >
                    {conversation.title}
                  </button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        className="mr-1 size-6 shrink-0"
                        aria-label={`Actions for ${conversation.title}`}
                      >
                        <MoreHorizontal className="size-3.5" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-40">
                      <DropdownMenuItem onSelect={() => beginRename(conversation)}>
                        <Pencil />
                        Rename
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        variant="destructive"
                        onSelect={() => void deleteConversation(conversation)}
                      >
                        <Trash2 />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>
            ))}
          </nav>
        )}

        <Conversation className="min-h-0 flex-1">
          <ConversationContent className="mx-auto w-full max-w-4xl flex-1 gap-6 px-4 py-6 sm:px-6 sm:py-8">
            {entries.length === 0 ? (
              <ConversationEmptyState
                className="min-h-[min(55vh,460px)]"
                icon={
                  <div className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-primary/10">
                    <AmberMark className="size-7" />
                  </div>
                }
                title="What can I help you with?"
                description="Ask a question and follow the assistant's tool activity and results as it works."
              />
            ) : (
              entries.map((entry) => (
                <Message
                  from={entry.kind === "text" ? entry.role : "assistant"}
                  key={entry.id}
                  className="max-w-full"
                >
                  {entry.kind === "text" && entry.role === "user" ? (
                    <MessageContent className="max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary/12 px-4 py-3 text-[15px] leading-6">
                      {entry.text}
                    </MessageContent>
                  ) : entry.kind === "text" ? (
                    <div className="flex w-full gap-3">
                      <AmberMark className="mt-1 size-6 shrink-0" />
                      <MessageContent className="min-w-0 flex-1 overflow-visible">
                        <MessageResponse isAnimating={loading}>
                          {entry.text}
                        </MessageResponse>
                      </MessageContent>
                    </div>
                  ) : (
                    <div className="flex w-full gap-3">
                      <AmberMark className="mt-1 size-6 shrink-0" />
                      <MessageContent className="min-w-0 flex-1 overflow-visible">
                        <ToolElement tool={entry} />
                      </MessageContent>
                    </div>
                  )}
                </Message>
              ))
            )}
            {loading && (
              <Message from="assistant" className="max-w-full">
                <div className="flex w-full gap-3">
                  <AmberMark className="mt-1 size-6 shrink-0" />
                  <MessageContent className="min-w-0 flex-1 overflow-visible">
                    <Shimmer duration={1}>Working through your request…</Shimmer>
                  </MessageContent>
                </div>
              </Message>
            )}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>

        <div className="border-t bg-background/40 p-3 sm:px-6 sm:py-4">
          <PromptInput
            onSubmit={({ text }) => send(text)}
            className="mx-auto max-w-4xl"
          >
            <PromptInputTextarea
              value={draft}
              onChange={(event) => setDraft(event.currentTarget.value)}
              maxLength={2000}
              disabled={loading}
              placeholder="Message Amber…"
              className="min-h-12 max-h-40 text-[15px]"
            />
            <PromptInputSubmit
              status={loading ? "streaming" : "ready"}
              disabled={!draft.trim() || loading}
              className="mr-1 mb-1"
            />
          </PromptInput>
          <p className="mx-auto mt-2 max-w-4xl text-center text-[11px] text-muted-foreground">
            Enter to send · Shift + Enter for a new line
          </p>
        </div>
      </section>
      <Dialog
        open={editingId !== null}
        onOpenChange={(open) => {
          if (!open && savingConversationId === null) {
            setEditingId(null)
          }
        }}
      >
        <DialogContent>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (editingId) void saveRename(editingId)
            }}
          >
            <DialogHeader>
              <DialogTitle>Rename conversation</DialogTitle>
              <DialogDescription>
                Choose a name that will help you find this conversation later.
              </DialogDescription>
            </DialogHeader>
            <Input
              autoFocus
              aria-label="Conversation name"
              value={editingTitle}
              maxLength={255}
              onChange={(event) => setEditingTitle(event.currentTarget.value)}
              className="my-4"
            />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditingId(null)}
                disabled={savingConversationId !== null}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={!editingTitle.trim() || savingConversationId !== null}
              >
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
