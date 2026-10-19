"use client"

import { useState } from "react"
import {
  AlertTriangle,
  BarChart3,
  Brain,
  CheckCircle2,
  CircleDashed,
  Clock,
  FileSearch,
  FileText,
  Globe,
  HardDrive,
  ListChecks,
  type LucideIcon,
  Search,
  Sheet as SheetIcon,
  ShieldCheck,
  Wrench,
  XCircle,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import {
  describeToolStep,
  exactTime,
  extraInputs,
  formatDuration,
  humanizeTool,
  matchPercent,
  personName,
  timeAgo,
  type TraceDetail,
  type TraceSource,
  type TraceStatus,
  type TraceStep,
  type TraceSummary,
  traceStatusLabel,
} from "@/lib/admin-activity"
import { cn } from "@/lib/utils"

import { useAdminNav } from "./admin-nav"
import { useAdminData } from "./use-admin-data"
import { useDebounced, usePagedAdmin } from "./use-paged-admin"

function toolIcon(tool: string): LucideIcon {
  if (tool === "vector_search") return FileSearch
  if (tool === "web_search") return Globe
  if (tool === "read_google_sheet" || tool.includes("sheet")) return SheetIcon
  if (tool === "get_file" || tool.includes("doc")) return FileText
  if (tool.startsWith("drive_")) return HardDrive
  if (tool.startsWith("render_")) return BarChart3
  if (tool === "update_task_list") return ListChecks
  return Wrench
}

const statusStyle: Record<TraceStatus, string> = {
  completed: "bg-success/15 text-success",
  failed: "bg-destructive/15 text-destructive",
  awaiting_approval: "bg-warning/15 text-warning",
}

function StatusBadge({ status }: { status: TraceStatus }) {
  return <Badge className={cn("border-transparent", statusStyle[status])}>{traceStatusLabel[status]}</Badge>
}

function ToolIcons({ tools }: { tools: string[] }) {
  if (tools.length === 0) return <span className="text-xs text-muted-foreground">Answered directly</span>
  const shown = tools.slice(0, 4)
  return (
    <span className="flex items-center gap-1">
      {shown.map((tool) => {
        const Icon = toolIcon(tool)
        return (
          <Tooltip key={tool}>
            <TooltipTrigger asChild>
              <span className="grid size-6 place-items-center rounded-md bg-muted text-muted-foreground">
                <Icon className="size-3.5" aria-label={humanizeTool(tool)} />
              </span>
            </TooltipTrigger>
            <TooltipContent>{humanizeTool(tool)}</TooltipContent>
          </Tooltip>
        )
      })}
      {tools.length > shown.length && (
        <span className="text-xs text-muted-foreground">+{tools.length - shown.length}</span>
      )}
    </span>
  )
}

export function TracesTab() {
  const { requestedTraceId, clearRequestedTrace } = useAdminNav()
  const [status, setStatus] = useState<TraceStatus | "all">("all")
  const [user, setUser] = useState("all")
  const [text, setText] = useState("")
  const [openId, setOpenId] = useState<string | null>(null)
  const q = useDebounced(text.trim())
  const { data: usersData } = useAdminData<{ users: { id: string; email: string; name: string }[] }>(
    "/api/admin/users",
  )
  const { items, hasMore, loading, error, loadMore } = usePagedAdmin<TraceSummary>("/api/admin/traces", "traces", {
    status: status === "all" ? undefined : status,
    user: user === "all" ? undefined : user,
    q: q || undefined,
  })

  // A trace opened from the audit log shows until this tab opens another one or the panel closes.
  const shownId = openId ?? requestedTraceId
  function closeTrace() {
    setOpenId(null)
    clearRequestedTrace()
  }

  const filtered = status !== "all" || user !== "all" || q !== ""

  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-sm text-muted-foreground">
        Every chat question, with what Amber did to answer it: the tools it ran, the sources it found and how long it
        took. Traces never include passage text or Amber&apos;s answer.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Search questions"
            className="pl-8"
            aria-label="Search questions"
          />
        </div>
        <Select value={status} onValueChange={(value) => setStatus(value as TraceStatus | "all")}>
          <SelectTrigger className="w-48" aria-label="Filter by outcome">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All outcomes</SelectItem>
            {(Object.keys(traceStatusLabel) as TraceStatus[]).map((s) => (
              <SelectItem key={s} value={s}>
                {traceStatusLabel[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={user} onValueChange={setUser}>
          <SelectTrigger className="w-48" aria-label="Filter by person">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Everyone</SelectItem>
            {(usersData?.users ?? []).map((u) => (
              <SelectItem key={u.id} value={u.id}>
                {u.name || u.email}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          Couldn&apos;t load query traces: {error}
        </p>
      )}

      <div className="overflow-hidden rounded-2xl border bg-card/40">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Question</TableHead>
              <TableHead>Asked by</TableHead>
              <TableHead>When</TableHead>
              <TableHead>What Amber used</TableHead>
              <TableHead className="text-right">Sources</TableHead>
              <TableHead className="text-right">Took</TableHead>
              <TableHead className="pr-4">Outcome</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((t) => (
              <TableRow key={t.id} className="cursor-pointer" onClick={() => setOpenId(t.id)}>
                <TableCell className="max-w-[320px] pl-4 whitespace-normal">
                  <button
                    type="button"
                    className="line-clamp-2 text-left font-medium hover:text-primary"
                    onClick={(e) => {
                      e.stopPropagation()
                      setOpenId(t.id)
                    }}
                  >
                    {t.kind === "approval" && <ShieldCheck className="mr-1 inline size-3.5 text-muted-foreground" />}
                    {t.question}
                  </button>
                </TableCell>
                <TableCell className="text-muted-foreground">{personName(t.user)}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">
                  <time dateTime={t.at} title={exactTime(t.at)}>
                    {timeAgo(t.at)}
                  </time>
                </TableCell>
                <TableCell>
                  <ToolIcons tools={t.tools} />
                </TableCell>
                <TableCell className="text-right tabular-nums">{t.source_count || "—"}</TableCell>
                <TableCell className="text-right tabular-nums">{formatDuration(t.latency_ms)}</TableCell>
                <TableCell className="pr-4">
                  <StatusBadge status={t.status} />
                </TableCell>
              </TableRow>
            ))}
            {!loading && items.length === 0 && !error && (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                  {filtered ? "No questions match these filters." : "No chat questions have been traced yet."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      {loading && (
        <p role="status" className="flex items-center justify-center gap-2 py-2 text-sm text-muted-foreground">
          <Spinner /> Loading traces…
        </p>
      )}
      {hasMore && !loading && (
        <div className="flex justify-center">
          <Button variant="outline" onClick={() => void loadMore()}>
            Show older questions
          </Button>
        </div>
      )}

      <Sheet open={shownId !== null} onOpenChange={(open) => !open && closeTrace()}>
        <SheetContent className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-none data-[side=right]:lg:w-[40vw]">
          {shownId && <TraceDetailView key={shownId} traceId={shownId} />}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border bg-card/60 px-3 py-2" title={hint}>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-sm font-medium tabular-nums">{value}</div>
    </div>
  )
}

function TraceDetailView({ traceId }: { traceId: string }) {
  const { data, error } = useAdminData<TraceDetail>(`/api/admin/traces/${traceId}`)

  if (error) {
    return (
      <SheetHeader>
        <SheetTitle>Trace unavailable</SheetTitle>
        <SheetDescription role="alert">{error}</SheetDescription>
      </SheetHeader>
    )
  }
  if (!data) {
    return (
      <SheetHeader>
        <SheetTitle className="flex items-center gap-2">
          <Spinner /> Loading trace…
        </SheetTitle>
        <SheetDescription className="sr-only">Loading</SheetDescription>
      </SheetHeader>
    )
  }

  const sources = uniqueSources(data.steps)
  const tokens =
    data.prompt_tokens || data.completion_tokens
      ? `${(data.prompt_tokens ?? 0).toLocaleString()} in · ${(data.completion_tokens ?? 0).toLocaleString()} out`
      : "Not reported"

  return (
    <>
      <SheetHeader>
        <div className="mb-1">
          <StatusBadge status={data.status} />
        </div>
        <SheetTitle className="text-base leading-snug">{data.question}</SheetTitle>
        <SheetDescription>
          {data.kind === "approval" ? "Approval decision by " : "Asked by "}
          {personName(data.user)} ·{" "}
          <time dateTime={data.at} title={exactTime(data.at)}>
            {timeAgo(data.at)}
          </time>
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-6 px-4 pb-6">
        {data.error && (
          <div role="alert" className="flex gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
            <div>
              <div className="font-medium">This answer didn&apos;t finish</div>
              <div className="text-muted-foreground">{data.error}</div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Took" value={formatDuration(data.latency_ms)} />
          <Stat label="Tool calls" value={String(data.tool_calls)} hint={data.failed_tools ? `${data.failed_tools} failed` : undefined} />
          <Stat label="Sources found" value={String(sources.length)} />
          <Stat label="Tokens" value={tokens} />
        </div>

        <section>
          <h3 className="mb-3 text-sm font-semibold">What Amber did</h3>
          {data.steps.length === 0 ? (
            <p className="text-sm text-muted-foreground">No steps were recorded.</p>
          ) : (
            <ol className="relative space-y-3 border-l pl-5">
              {data.steps.map((step, index) => (
                <StepItem key={index} step={step} />
              ))}
            </ol>
          )}
        </section>

        {sources.length > 0 && (
          <section>
            <h3 className="mb-2 text-sm font-semibold">Sources it found</h3>
            <div className="overflow-hidden rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-3">Document</TableHead>
                    <TableHead>Page</TableHead>
                    <TableHead className="w-40 pr-3">Match</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sources.map((source) => {
                    const match = matchPercent(source)
                    return (
                      <TableRow key={`${source.document_id}-${source.page ?? ""}`}>
                        <TableCell className="max-w-[260px] truncate pl-3 font-medium">
                          {source.title || "Untitled document"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{source.page ?? "—"}</TableCell>
                        <TableCell className="pr-3">
                          {match === null ? (
                            <span className="text-xs text-muted-foreground">Keyword match</span>
                          ) : (
                            <span className="flex items-center gap-2">
                              <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                                <span className="block h-full rounded-full bg-primary" style={{ width: `${match}%` }} />
                              </span>
                              <span className="text-xs tabular-nums">{match}%</span>
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </section>
        )}

        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-xs">
          <dt className="text-muted-foreground">Model</dt>
          <dd>{data.model ?? "Unknown"}</dd>
          <dt className="text-muted-foreground">Asked at</dt>
          <dd>{exactTime(data.at)}</dd>
          <dt className="text-muted-foreground">Account</dt>
          <dd>{data.user.email}</dd>
          {data.conversation_id && (
            <>
              <dt className="text-muted-foreground">Conversation</dt>
              <dd className="break-all">{data.conversation_id}</dd>
            </>
          )}
          <dt className="text-muted-foreground">Trace ID</dt>
          <dd className="break-all">{data.id}</dd>
        </dl>
        <p className="text-xs text-muted-foreground">
          Traces show what Amber did, not what it read. Passage text and answers are never stored, so admins see
          document names and match scores only.
        </p>
      </div>
    </>
  )
}

function StepItem({ step }: { step: TraceStep }) {
  if (step.type === "model") {
    return (
      <li className="relative">
        <StepDot icon={Brain} tone="muted" />
        <div className="text-sm">
          {step.decision === "answer" ? "Wrote the answer" : "Decided which tools to use"}
          <span className="ml-2 text-xs text-muted-foreground tabular-nums">{formatDuration(step.duration_ms)}</span>
        </div>
      </li>
    )
  }

  const Icon = toolIcon(step.tool)
  const extras = extraInputs(step)
  const tone = step.status === "failed" ? "bad" : step.status === "completed" ? "good" : "muted"
  const StatusIcon = step.status === "failed" ? XCircle : step.status === "completed" ? CheckCircle2 : CircleDashed
  return (
    <li className="relative">
      <StepDot icon={Icon} tone={tone} />
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-x-2 text-sm">
          <span className="font-medium">{describeToolStep(step)}</span>
          <StatusIcon
            className={cn(
              "size-3.5",
              tone === "good" && "text-success",
              tone === "bad" && "text-destructive",
              tone === "muted" && "text-muted-foreground",
            )}
            aria-label={step.status}
          />
          <span className="flex items-center gap-1 text-xs text-muted-foreground tabular-nums">
            <Clock className="size-3" aria-hidden /> {formatDuration(step.duration_ms)}
          </span>
        </div>
        {step.sources && (
          <p className="text-xs text-muted-foreground">
            {step.sources.length === 0
              ? "Found nothing relevant"
              : `Found ${step.sources.length} passage${step.sources.length === 1 ? "" : "s"} in ${
                  new Set(step.sources.map((s) => s.document_id)).size
                } document${new Set(step.sources.map((s) => s.document_id)).size === 1 ? "" : "s"}`}
          </p>
        )}
        {step.status === "stopped" && <p className="text-xs text-muted-foreground">Stopped before it finished</p>}
        {step.error && <p className="text-xs break-words text-destructive">{step.error}</p>}
        {extras.length > 0 && (
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-0.5 text-xs">
            {extras.map((row) => (
              <div key={row.label} className="contents">
                <dt className="text-muted-foreground">{row.label}</dt>
                <dd className="break-all">{row.value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </li>
  )
}

function StepDot({ icon: Icon, tone }: { icon: LucideIcon; tone: "good" | "bad" | "muted" }) {
  return (
    <span
      className={cn(
        "absolute top-0 -left-[31px] grid size-5 place-items-center rounded-full border bg-background",
        tone === "bad" && "border-destructive/50 text-destructive",
        tone === "good" && "text-foreground",
        tone === "muted" && "text-muted-foreground",
      )}
    >
      <Icon className="size-3" aria-hidden />
    </span>
  )
}

function uniqueSources(steps: TraceStep[]): TraceSource[] {
  const seen = new Map<string, TraceSource>()
  for (const step of steps) {
    if (step.type !== "tool") continue
    for (const source of step.sources ?? []) {
      const key = `${source.document_id}-${source.page ?? ""}`
      const existing = seen.get(key)
      if (!existing || (matchPercent(source) ?? -1) > (matchPercent(existing) ?? -1)) seen.set(key, source)
    }
  }
  return [...seen.values()].sort((a, b) => (matchPercent(b) ?? -1) - (matchPercent(a) ?? -1))
}
