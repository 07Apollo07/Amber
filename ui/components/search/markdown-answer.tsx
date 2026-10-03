"use client"

import ReactMarkdown from "react-markdown"
import rehypeSanitize from "rehype-sanitize"

import { CitationChip } from "./citation-chip"

/**
 * Renders model output. LLM text and document content are untrusted, so raw HTML is
 * never rendered and the tree is sanitized. Citations arrive as `[n](#cite-n)` links.
 */
export function MarkdownAnswer({ markdown, onCite }: { markdown: string; onCite: (n: number) => void }) {
  return (
    <div className="prose-amber text-[15px] leading-7 text-foreground/90">
      <ReactMarkdown
        skipHtml
        rehypePlugins={[rehypeSanitize]}
        components={{
          p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5">{children}</ol>,
          code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 text-[13px]">{children}</code>,
          a: ({ href, children }) => {
            const match = href?.match(/^#cite-(\d+)$/)
            if (match) return <CitationChip n={Number(match[1])} onClick={onCite} />
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline-offset-4 hover:underline">
                {children}
              </a>
            )
          },
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  )
}
