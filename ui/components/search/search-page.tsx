"use client"

import { useState } from "react"
import { MessagesSquare, Zap } from "lucide-react"

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type { Answer, Source } from "@/lib/types"

import { ChatView } from "./chat-view"
import { emptyFilters, FilterBar, type Filters } from "./filter-bar"
import { QuickSearch } from "./quick-search"
import { SourcePreviewSheet } from "./source-preview-sheet"

type Mode = "quick" | "chat"

export function SearchPage() {
  const [mode, setMode] = useState<Mode>("quick")
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [preview, setPreview] = useState<Source | null>(null)

  function openCitation(answer: Answer, n: number) {
    setPreview(answer.sources.find((s) => s.n === n) ?? null)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <ToggleGroup
          type="single"
          value={mode}
          onValueChange={(value) => value && setMode(value as Mode)}
          variant="outline"
          aria-label="Search mode"
          className="rounded-xl bg-card/60 p-1"
          spacing={1}
        >
          <ToggleGroupItem value="quick" className="h-8 gap-1.5 rounded-lg border-0 px-3 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground">
            <Zap className="size-4" /> Quick answer
          </ToggleGroupItem>
          <ToggleGroupItem value="chat" className="h-8 gap-1.5 rounded-lg border-0 px-3 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground">
            <MessagesSquare className="size-4" /> Chat
          </ToggleGroupItem>
        </ToggleGroup>
        <FilterBar filters={filters} onChange={setFilters} />
      </div>

      {mode === "quick" ? <QuickSearch onCite={openCitation} /> : <ChatView onCite={openCitation} />}

      <SourcePreviewSheet source={preview} onClose={() => setPreview(null)} />
    </div>
  )
}
