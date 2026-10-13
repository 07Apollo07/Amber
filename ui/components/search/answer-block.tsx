"use client"

import type { Answer, Source } from "@/lib/types"

import { FeedbackBar } from "./feedback-bar"
import { MarkdownAnswer } from "./markdown-answer"
import { SourceList } from "./source-list"
import { TracePanel } from "./trace-panel"

/** Answer, feedback, sources and trace. Shared by Quick and Chat modes. */
export function AnswerBlock({
  answer,
  onCite,
  onOpenSource,
}: {
  answer: Answer
  onCite: (n: number) => void
  onOpenSource?: (source: Source) => void
}) {
  return (
    <div className="space-y-5">
      <MarkdownAnswer
        markdown={answer.markdown}
        onCite={onCite}
        sources={answer.sources}
        onOpenSource={onOpenSource || ((source) => onCite(source.n))}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FeedbackBar copyText={answer.markdown.replace(/\[(\d+)\]\(#cite-\d+\)/g, "[$1]")} />
        <span className="text-xs text-muted-foreground">
          Answers can be wrong. Check the sources.
        </span>
      </div>
      {answer.sources && answer.sources.length > 0 && <SourceList sources={answer.sources} onOpen={onCite} />}
      {answer.trace && answer.trace.chunks && answer.trace.chunks.length > 0 && <TracePanel trace={answer.trace} />}
    </div>
  )
}
