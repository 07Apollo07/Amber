"use client"

import { useState } from "react"
import { ArrowRight, Search, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { sampleAnswer } from "@/lib/mock-data"
import type { Answer } from "@/lib/types"

import { AnswerBlock } from "./answer-block"

const suggestions = [
  "What's our remote work policy?",
  "Summarize the Q3 board update",
  "Who approves vendor contracts over $50k?",
  "What are the steps after a security incident?",
]

export function QuickSearch({ onCite }: { onCite: (answer: Answer, n: number) => void }) {
  const [query, setQuery] = useState("")
  const [state, setState] = useState<"idle" | "loading" | "done">("idle")
  const [answer, setAnswer] = useState<Answer | null>(null)

  function run(text: string) {
    const q = text.trim()
    if (!q) return
    setQuery(q)
    setState("loading")
    // Phase 1: show the canned answer after a short pause instead of calling the API.
    setTimeout(() => {
      setAnswer({ ...sampleAnswer, trace: { ...sampleAnswer.trace, query: q } })
      setState("done")
    }, 900)
  }

  return (
    <div className="mx-auto max-w-3xl">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          run(query)
        }}
        className="group relative"
      >
        <Search className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-muted-foreground transition-colors group-focus-within:text-primary" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Ask anything about your documents…"
          aria-label="Search question"
          maxLength={2000}
          autoFocus
          className="h-14 w-full rounded-2xl border border-input bg-card/80 pr-28 pl-12 text-base shadow-lg shadow-black/20 transition-colors outline-none placeholder:text-muted-foreground focus:border-primary/60 focus:ring-4 focus:ring-primary/15"
        />
        <Button type="submit" disabled={!query.trim() || state === "loading"} className="absolute top-1/2 right-2.5 h-9 -translate-y-1/2 px-4">
          Ask <ArrowRight />
        </Button>
      </form>

      {state === "idle" && (
        <div className="mt-10">
          <p className="mb-3 flex items-center gap-1.5 text-sm text-muted-foreground">
            <Sparkles className="size-4 text-primary" /> Try asking
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => run(s)}
                className="rounded-xl border bg-card/50 px-4 py-3 text-left text-sm transition-colors hover:border-primary/40 hover:bg-card"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {state === "loading" && (
        <div className="mt-8 space-y-3" aria-live="polite" aria-busy="true">
          <span className="sr-only">Searching…</span>
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-10/12" />
          <Skeleton className="h-4 w-8/12" />
          <div className="grid gap-2 pt-4 sm:grid-cols-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
        </div>
      )}

      {state === "done" && answer && (
        <article className="mt-8 rounded-2xl border bg-card/60 p-5 sm:p-6" aria-live="polite">
          <AnswerBlock answer={answer} onCite={(n) => onCite(answer, n)} />
        </article>
      )}
    </div>
  )
}
