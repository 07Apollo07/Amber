"use client"

import { useState } from "react"
import { ArrowRight, Search, Unplug } from "lucide-react"

import { EmptyState } from "@/components/app/empty-state"
import { Button } from "@/components/ui/button"
import { demoAction } from "@/lib/demo"
import type { Answer } from "@/lib/types"

import { AnswerBlock } from "./answer-block"

export function QuickSearch({ onCite }: { onCite: (answer: Answer, n: number) => void }) {
  const [query, setQuery] = useState("")
  const [submitted, setSubmitted] = useState(false)
  // Filled by the search API in Phase 5.
  const [answer] = useState<Answer | null>(null)

  return (
    <div className="mx-auto max-w-3xl">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!query.trim()) return
          setSubmitted(true)
          demoAction("Search", "Search isn't connected to the backend yet.")
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
        <Button type="submit" disabled={!query.trim()} className="absolute top-1/2 right-2.5 h-9 -translate-y-1/2 px-4">
          Ask <ArrowRight />
        </Button>
      </form>

      {answer ? (
        <article className="mt-8 rounded-2xl border bg-card/60 p-5 sm:p-6" aria-live="polite">
          <AnswerBlock answer={answer} onCite={(n) => onCite(answer, n)} />
        </article>
      ) : (
        submitted && (
          <EmptyState
            className="mt-8 rounded-2xl border border-dashed"
            icon={Unplug}
            title="No answer yet"
            description="Search isn't connected to the backend yet. Answers with sources will appear here."
          />
        )
      )}
    </div>
  )
}
