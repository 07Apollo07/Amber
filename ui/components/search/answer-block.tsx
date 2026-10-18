"use client"

import type { Answer, Source } from "@/lib/types"

import { FeedbackBar } from "./feedback-bar"
import { MarkdownAnswer } from "./markdown-answer"
import { SourceList } from "./source-list"
import { TracePanel } from "./trace-panel"
import { ToolElement } from "./tool-element"

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
  const toolCalls = answer.toolCalls || answer.trace?.toolCalls
  return (
    <div className="space-y-5">
      {toolCalls && toolCalls.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Tool Executions</div>
          <div className="space-y-2">
            {toolCalls.map((tool) => (
              <ToolElement key={tool.id} tool={tool} />
            ))}
          </div>
        </div>
      )}
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
