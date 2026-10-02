"use client"

import { useEffect, useRef, useState } from "react"
import { ArrowUp, MessageSquare, PanelLeft, Plus, Trash2 } from "lucide-react"

import { AmberMark } from "@/components/app/amber-logo"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { demoAction } from "@/lib/demo"
import { chatMessages, conversations, sampleAnswer } from "@/lib/mock-data"
import type { Answer, ChatMessage } from "@/lib/types"
import { cn } from "@/lib/utils"

import { AnswerBlock } from "./answer-block"

function ConversationList({
  activeId,
  onSelect,
  onNew,
}: {
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
}) {
  return (
    <div className="flex h-full flex-col gap-2">
      <Button variant="outline" className="justify-start" onClick={onNew}>
        <Plus /> New chat
      </Button>
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
                onClick={() => demoAction("Conversation deleted")}
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

export function ChatView({ onCite }: { onCite: (answer: Answer, n: number) => void }) {
  const [activeId, setActiveId] = useState<string | null>("c_1")
  const [messages, setMessages] = useState<ChatMessage[]>(chatMessages)
  const [draft, setDraft] = useState("")
  const [thinking, setThinking] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages, thinking])

  function send() {
    const text = draft.trim()
    if (!text || thinking) return
    setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", text }])
    setDraft("")
    setThinking(true)
    // Phase 1: canned reply instead of the streaming API.
    setTimeout(() => {
      setMessages((m) => [
        ...m,
        { id: crypto.randomUUID(), role: "assistant", answer: { ...sampleAnswer, trace: { ...sampleAnswer.trace, query: text } } },
      ])
      setThinking(false)
    }, 1000)
  }

  function newChat() {
    setActiveId(null)
    setMessages([])
    setDrawerOpen(false)
  }

  function select(id: string) {
    setActiveId(id)
    setMessages(chatMessages)
    setDrawerOpen(false)
  }

  return (
    <div className="flex h-[calc(100dvh-14rem)] min-h-[520px] gap-4">
      <aside className="hidden w-64 shrink-0 lg:block">
        <ConversationList activeId={activeId} onSelect={select} onNew={newChat} />
      </aside>

      <section className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-card/40">
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
              <ConversationList activeId={activeId} onSelect={select} onNew={newChat} />
            </SheetContent>
          </Sheet>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
          {messages.length === 0 && !thinking ? (
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
                      <AnswerBlock answer={message.answer} onCite={(n) => onCite(message.answer, n)} />
                    </div>
                  </div>
                ),
              )}
              {thinking && (
                <div className="flex items-center gap-3 text-sm text-muted-foreground" aria-live="polite">
                  <AmberMark className="size-6 animate-pulse" />
                  Searching your documents…
                </div>
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
              className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-muted-foreground"
            />
            <Button type="submit" size="icon" aria-label="Send" disabled={!draft.trim() || thinking}>
              <ArrowUp />
            </Button>
          </div>
          <p className="mt-1.5 text-center text-[11px] text-muted-foreground">Enter to send · Shift + Enter for a new line</p>
        </form>
      </section>
    </div>
  )
}
