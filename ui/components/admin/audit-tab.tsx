"use client"

import { useMemo, useState } from "react"
import { ChevronRight, Download, Route, Search } from "lucide-react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Spinner } from "@/components/ui/spinner"
import {
  type AuditCategory,
  type AuditEvent,
  categoryLabel,
  clockTime,
  dayLabel,
  describeAuditEvent,
  detailRows,
  exactTime,
  personName,
  timeAgo,
} from "@/lib/admin-activity"
import { initials } from "@/lib/format"
import { cn } from "@/lib/utils"

import { useAdminNav } from "./admin-nav"
import { type RangePreset, rangeLabel, rangeStart, useDebounced, usePagedAdmin } from "./use-paged-admin"

type Actor = { id: string; email: string; name: string | null }

const categoryStyle: Record<AuditCategory, string> = {
  sign_in: "bg-chart-2/15 text-chart-2",
  chat: "bg-primary/15 text-primary",
  documents: "bg-chart-3/15 text-chart-3",
  collections: "bg-chart-5/20 text-foreground/80",
  sharing: "bg-chart-4/15 text-chart-4",
  drive: "bg-chart-2/10 text-chart-2",
  admin: "bg-warning/15 text-warning",
  other: "bg-muted text-muted-foreground",
}

const categories = Object.keys(categoryLabel) as AuditCategory[]

export function CategoryChip({ category }: { category: AuditCategory }) {
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap", categoryStyle[category])}>
      {categoryLabel[category]}
    </span>
  )
}

function EventRow({ event }: { event: AuditEvent }) {
  const [open, setOpen] = useState(false)
  const { openTrace } = useAdminNav()
  const who = personName(event.actor)
  const rows = detailRows(event)
  const traceId = typeof event.detail.trace_id === "string" ? event.detail.trace_id : null

  return (
    <li className="border-b last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none"
      >
        <Avatar className="mt-0.5 size-7 shrink-0">
          <AvatarFallback className="text-[10px]">{initials(who)}</AvatarFallback>
        </Avatar>
        <span className="min-w-0 flex-1">
          <span className="block text-sm leading-snug">
            <span className="font-medium">{who}</span> {describeAuditEvent(event)}
          </span>
          {event.actor.name && event.actor.email && (
            <span className="block truncate text-xs text-muted-foreground">{event.actor.email}</span>
          )}
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center sm:gap-3">
          <CategoryChip category={event.category} />
          <time
            dateTime={event.at}
            title={`${exactTime(event.at)} (${timeAgo(event.at)})`}
            className="text-xs text-muted-foreground tabular-nums"
          >
            {clockTime(event.at)}
          </time>
        </span>
        <ChevronRight
          className={cn("mt-1 size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
          aria-hidden
        />
      </button>
      {open && (
        <div className="space-y-3 bg-muted/20 px-4 pt-1 pb-4 pl-14">
          <dl className="grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-[max-content_1fr]">
            <dt className="text-muted-foreground">When</dt>
            <dd>{exactTime(event.at)}</dd>
            {rows.map((row) => (
              <div key={row.label} className="contents">
                <dt className="text-muted-foreground">{row.label}</dt>
                <dd className="break-all">{row.value}</dd>
              </div>
            ))}
            <dt className="text-muted-foreground">Event code</dt>
            <dd>
              <code className="rounded bg-muted px-1.5 py-0.5">{event.action}</code>
            </dd>
          </dl>
          {traceId && (
            <Button size="sm" variant="outline" onClick={() => openTrace(traceId)}>
              <Route /> View query trace
            </Button>
          )}
        </div>
      )}
    </li>
  )
}

export function AuditTab() {
  const [category, setCategory] = useState<AuditCategory | "all">("all")
  const [actor, setActor] = useState("all")
  const [range, setRange] = useState<RangePreset>("30d")
  const [from, setFrom] = useState(() => rangeStart("30d"))
  const [text, setText] = useState("")
  const q = useDebounced(text.trim())

  const { items, raw, hasMore, loading, error, loadMore, search } = usePagedAdmin<AuditEvent>(
    "/api/admin/audit",
    "events",
    {
      category: category === "all" ? undefined : category,
      actor: actor === "all" ? undefined : actor,
      from,
      q: q || undefined,
    },
  )
  const actors = (raw?.actors as Actor[] | undefined) ?? []

  const groups = useMemo(() => {
    const byDay: { day: string; events: AuditEvent[] }[] = []
    for (const event of items) {
      const day = dayLabel(event.at)
      const last = byDay.at(-1)
      if (last?.day === day) last.events.push(event)
      else byDay.push({ day, events: [event] })
    }
    return byDay
  }, [items])

  const filtered = category !== "all" || actor !== "all" || range !== "all" || q !== ""

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Search people, files, details"
            className="pl-8"
            aria-label="Search the audit log"
          />
        </div>
        <Select value={category} onValueChange={(value) => setCategory(value as AuditCategory | "all")}>
          <SelectTrigger className="w-40" aria-label="Filter by category">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All activity</SelectItem>
            {categories.map((c) => (
              <SelectItem key={c} value={c}>
                {categoryLabel[c]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={actor} onValueChange={setActor}>
          <SelectTrigger className="w-48" aria-label="Filter by person">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Everyone</SelectItem>
            {actors.map((a) => (
              <SelectItem key={a.id} value={a.id}>
                {a.name || a.email}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={range}
          onValueChange={(value) => {
            setRange(value as RangePreset)
            setFrom(rangeStart(value as RangePreset))
          }}
        >
          <SelectTrigger className="w-40" aria-label="Filter by date">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(rangeLabel) as RangePreset[]).map((r) => (
              <SelectItem key={r} value={r}>
                {rangeLabel[r]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" className="sm:ml-auto" asChild>
          <a href={`/api/admin/audit/export${search ? `?${search}` : ""}`} download>
            <Download /> Export CSV
          </a>
        </Button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          Couldn&apos;t load the audit log: {error}
        </p>
      )}

      <div className="space-y-5">
        {groups.map((group) => (
          <section key={group.day} aria-label={group.day}>
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{group.day}</h3>
            <ul className="overflow-hidden rounded-2xl border bg-card/40">
              {group.events.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
            </ul>
          </section>
        ))}
        {!loading && items.length === 0 && !error && (
          <p className="rounded-2xl border bg-card/40 py-10 text-center text-sm text-muted-foreground">
            {filtered ? "No activity matches these filters." : "No activity recorded yet."}
          </p>
        )}
        {loading && (
          <p role="status" className="flex items-center justify-center gap-2 py-4 text-sm text-muted-foreground">
            <Spinner /> Loading activity…
          </p>
        )}
        {hasMore && !loading && (
          <div className="flex justify-center">
            <Button variant="outline" onClick={() => void loadMore()}>
              Show older activity
            </Button>
          </div>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        The audit log is append-only: entries can&apos;t be edited or deleted. Times are shown in your time zone; the CSV
        export uses UTC and includes up to 10,000 rows.
      </p>
    </div>
  )
}
