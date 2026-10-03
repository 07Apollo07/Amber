"use client"

import { useState } from "react"
import { Check, Copy, MessageSquareText, ThumbsDown, ThumbsUp } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Textarea } from "@/components/ui/textarea"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { demoAction } from "@/lib/demo"
import { cn } from "@/lib/utils"

export function FeedbackBar({ copyText }: { copyText: string }) {
  const [vote, setVote] = useState<"up" | "down" | null>(null)
  const [copied, setCopied] = useState(false)
  const [comment, setComment] = useState("")

  function castVote(next: "up" | "down") {
    setVote((current) => (current === next ? null : next))
    demoAction(next === "up" ? "Marked helpful" : "Marked not helpful")
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(copyText)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      demoAction("Copy failed", "Your browser blocked clipboard access.")
    }
  }

  return (
    <div className="flex items-center gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Helpful"
            aria-pressed={vote === "up"}
            onClick={() => castVote("up")}
            className={cn(vote === "up" && "bg-success/15 text-success hover:bg-success/20 hover:text-success")}
          >
            <ThumbsUp />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Helpful</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Not helpful"
            aria-pressed={vote === "down"}
            onClick={() => castVote("down")}
            className={cn(vote === "down" && "bg-destructive/15 text-destructive hover:bg-destructive/20 hover:text-destructive")}
          >
            <ThumbsDown />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Not helpful</TooltipContent>
      </Tooltip>
      <Popover>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Add a comment">
                <MessageSquareText />
              </Button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent>Add a comment</TooltipContent>
        </Tooltip>
        <PopoverContent align="start" className="w-80">
          <form
            className="space-y-2"
            onSubmit={(event) => {
              event.preventDefault()
              demoAction("Feedback sent")
              setComment("")
            }}
          >
            <label htmlFor="feedback-comment" className="text-sm font-medium">
              What could be better?
            </label>
            <Textarea
              id="feedback-comment"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="e.g. It missed the 2025 version of this policy"
              maxLength={1000}
            />
            <Button type="submit" size="sm" disabled={!comment.trim()} className="w-full">
              Send feedback
            </Button>
          </form>
        </PopoverContent>
      </Popover>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label="Copy answer" onClick={copy}>
            {copied ? <Check className="text-success" /> : <Copy />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{copied ? "Copied" : "Copy answer"}</TooltipContent>
      </Tooltip>
    </div>
  )
}
