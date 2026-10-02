"use client"

import type { Answer } from "@/lib/types"

import { FeedbackBar } from "./feedback-bar"
import { MarkdownAnswer } from "./markdown-answer"
import { SourceList } from "./source-list"
import { TracePanel } from "./trace-panel"

/** Answer, feedback, sources and trace. Shared by Quick and Chat modes. */
export function AnswerBlock({
  answer,
  onCite,
}: {
  answer: Answer
  onCite: (n: number) => void
}) {
  return (
    <div className="space-y-5">
      <MarkdownAnswer markdown={answer.markdown} onCite={onCite} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FeedbackBar copyText={answer.markdown.replace(/\[(\d+)\]\(#cite-\d+\)/g, "[$1]")} />
        <span className="text-xs text-muted-foreground">
          Answers can be wrong. Check the sources.
        </span>
      </div>
      <SourceList sources={answer.sources} onOpen={onCite} />
      <TracePanel trace={answer.trace} />
    </div>
  )
}
