"use client"

import ReactMarkdown from "react-markdown"
import rehypeSanitize from "rehype-sanitize"
import type { ReactNode } from "react"

import type { Source } from "@/lib/types"

import { CitationChip } from "./citation-chip"
import { InternalDocChip } from "./internal-doc-chip"

/**
 * Renders model output. LLM text and document content are untrusted, so raw HTML is
 * never rendered and the tree is sanitized. Citations arrive as `[n](#cite-n)` links.
 */
export function MarkdownAnswer({
  markdown,
  onCite,
  sources = [],
  onOpenSource,
}: {
  markdown: string
  onCite: (n: number) => void
  sources?: Source[]
  onOpenSource?: (source: Source) => void
}) {
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
          a: ({ href, children }: { href?: string; children?: ReactNode }) => {
            const match = href?.match(/^#cite-(\d+)$/)
            if (match) return <CitationChip n={Number(match[1])} onClick={onCite} />

                      // Extract text content from children (could be string, array, or React elements)
                      let childText = ""
                      if (typeof children === "string") {
                        childText = children
                      } else if (Array.isArray(children)) {
                        childText = children
                                                .map((c) => {
                                                  if (typeof c === "string") return c
                                                  if (c && typeof c === "object" && "props" in c) {
                                                    const element = c as { props?: { children?: string } }
                                                    return element.props?.children || ""
                                                  }
                                                  return ""
                                                })
                                                .join("")
                                            } else if (children && typeof children === "object" && "props" in children) {
                                              const element = children as { props?: { children?: string } }
                                              childText = element.props?.children || ""
                                            }

                      // Detect internal doc links by text content OR URL pattern
                      const isInternalDoc = 
                        childText.includes("Internal Doc") || 
                        childText.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i) ||
                        href?.includes("localhost:3000") ||
                        href?.match(/\/(\d+)(?:\.|$)/)

                      if (isInternalDoc && onOpenSource && (childText || href)) {
                        return (
                          <InternalDocChip
                            text={childText}
                            href={href}
                            sources={sources}
                            onOpenSource={onOpenSource}
                          />
                        )
                      }

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
