"use client"

import { useState, useSyncExternalStore } from "react"
import {
  BarChart3,
  CircleAlert,
  CircleCheck,
  FileText,
  Loader2,
  Minus,
  Table2,
  TrendingDown,
  TrendingUp,
  Wrench,
} from "lucide-react"

import { EmptyState } from "@/components/app/empty-state"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { exactTime, formatDuration, humanizeTool, timeAgo } from "@/lib/admin-activity"
import { cn } from "@/lib/utils"

import { useAdminNav } from "./admin-nav"
import { useAdminData } from "./use-admin-data"

type Window = {
  questions: number
  people: number
  completed: number
  failed: number
  awaiting_approval: number
  success_rate: number | null
  median_ms: number | null
  p95_ms: number | null
}

type Analytics = {
  range: { days: number; start: string; end: string; tz: string }
  current: Window
  previous: Window
  per_day: { day: string; questions: number; failed: number }[]
  tools: { tool: string; calls: number; failed: number; median_ms: number | null }[]
  sources: { document_id: string; title: string | null; answers: number; people: number }[]
  people: { id: string; email: string; name: string | null; questions: number; failed: number; last_asked: string | null }[]
  library: {
    total: number
    ready: number
    processing: number
    failed: number
    recent_failures: { id: string; title: string; file_type: string; message: string | null; updated_at: string }[]
  }
}

const RANGES = [7, 30, 90] as const

const noSubscription = () => () => undefined

function timeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
  } catch {
    return "UTC"
  }
}

/** "2026-10-19" → "Oct 19" (a calendar date, so no time-zone shift). */
function shortDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

type Trend = "good" | "bad" | null

/** Change against the previous window, phrased plainly. `higherIsBetter` decides the colour. */
function change(
  current: number | null,
  previous: number | null,
  format: (delta: number) => string,
  higherIsBetter: boolean,
): { text: string; trend: Trend; direction: "up" | "down" | "flat" } {
  if (current === null || previous === null) return { text: "No earlier data to compare", trend: null, direction: "flat" }
  const delta = current - previous
  if (Math.abs(delta) < 1e-9) return { text: "Same as the previous period", trend: null, direction: "flat" }
  const up = delta > 0
  return {
    text: `${up ? "+" : "−"}${format(Math.abs(delta))} vs previous period`,
    trend: up === higherIsBetter ? "good" : "bad",
    direction: up ? "up" : "down",
  }
}

function StatTile({
  label,
  value,
  note,
  delta,
}: {
  label: string
  value: string
  note?: string
  delta: ReturnType<typeof change>
}) {
  const Icon = delta.direction === "up" ? TrendingUp : delta.direction === "down" ? TrendingDown : Minus
  return (
    <div className="rounded-2xl border bg-card/60 p-5">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 text-3xl font-semibold tracking-tight tabular-nums">{value}</div>
      {note && <div className="text-xs text-muted-foreground">{note}</div>}
      <div
        className={cn(
          "mt-1 flex min-h-4 items-center gap-1 text-xs",
          delta.trend === "good" && "text-success",
          delta.trend === "bad" && "text-destructive",
          delta.trend === null && "text-muted-foreground",
        )}
      >
        <Icon className="size-3.5" aria-hidden />
        {delta.text}
      </div>
    </div>
  )
}

const TICK_COUNT = 4

/** Clean tick step (1/2/5 × 10^n) so the axis tops out just above the largest value. */
function niceTicks(max: number): number[] {
  const raw = Math.max(max, 1) / (TICK_COUNT - 1)
  const pow = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw
  return Array.from({ length: TICK_COUNT }, (_, i) => i * step)
}

/** Single-series column chart: one hue, no legend (the title names the series). */
function QuestionsChart({ data }: { data: Analytics["per_day"] }) {
  const [hover, setHover] = useState<number | null>(null)
  const [showTable, setShowTable] = useState(false)
  const total = data.reduce((sum, d) => sum + d.questions, 0)
  const ticks = niceTicks(Math.max(0, ...data.map((d) => d.questions)))
  const max = ticks[ticks.length - 1]
  const labelEvery = Math.max(1, Math.ceil(data.length / 7))

  return (
    <div className="rounded-2xl border bg-card/60 p-5">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium">Questions per day</h3>
          <p className="text-sm text-muted-foreground">
            {total.toLocaleString()} {total === 1 ? "question" : "questions"} in the last {data.length} days
          </p>
        </div>
        {total > 0 && (
          <Button variant="ghost" size="sm" aria-pressed={showTable} onClick={() => setShowTable((s) => !s)}>
            <Table2 /> {showTable ? "Show chart" : "Show table"}
          </Button>
        )}
      </div>

      {total === 0 ? (
        <EmptyState icon={BarChart3} title="No questions yet" description="Daily counts appear once people start chatting with Amber." />
      ) : showTable ? (
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Questions per day</caption>
            <thead className="sticky top-0 bg-card text-left text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="py-1.5 font-medium">Day</th>
                <th className="py-1.5 text-right font-medium">Questions</th>
                <th className="py-1.5 text-right font-medium">Failed</th>
              </tr>
            </thead>
            <tbody>
              {[...data].reverse().map((d) => (
                <tr key={d.day} className="border-b border-border/50 last:border-0">
                  <td className="py-1.5">{shortDay(d.day)}</td>
                  <td className="py-1.5 text-right tabular-nums">{d.questions}</td>
                  <td className="py-1.5 text-right tabular-nums">{d.failed || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div
          className="mt-6 flex gap-2"
          role="group"
          aria-label={`Questions per day, ${total} in total. Each column is a button showing its value.`}
        >
          <div className="relative h-48 w-8 shrink-0 text-right text-[11px] text-muted-foreground tabular-nums" aria-hidden="true">
            {ticks.map((t) => (
              <span key={t} className="absolute right-0 translate-y-1/2" style={{ bottom: `${(t / max) * 100}%` }}>
                {t.toLocaleString()}
              </span>
            ))}
          </div>
          <div className="min-w-0 flex-1">
            <div className="relative h-48">
              {ticks.map((t) => (
                <div
                  key={t}
                  className="absolute inset-x-0 border-t border-border/70"
                  style={{ bottom: `${(t / max) * 100}%` }}
                  aria-hidden="true"
                />
              ))}
              <div className="absolute inset-0 flex items-end gap-[2px]">
                {data.map((d, i) => (
                  <button
                    key={d.day}
                    type="button"
                    className="relative flex h-full flex-1 items-end justify-center outline-none"
                    onPointerEnter={() => setHover(i)}
                    onPointerLeave={() => setHover(null)}
                    onFocus={() => setHover(i)}
                    onBlur={() => setHover(null)}
                    aria-label={`${shortDay(d.day)}: ${d.questions} questions${d.failed ? `, ${d.failed} failed` : ""}`}
                  >
                    <span
                      className={cn(
                        "block w-full max-w-6 rounded-t-[4px] bg-chart-1 transition-[filter]",
                        hover === i && "brightness-125",
                      )}
                      style={{ height: `${(d.questions / max) * 100}%` }}
                    />
                    {hover === i && (
                      <span
                        className={cn(
                          "pointer-events-none absolute z-10 -translate-y-2 rounded-lg border bg-popover px-2.5 py-1.5 text-left whitespace-nowrap shadow-lg",
                          i > data.length / 2 ? "right-0" : "left-0",
                        )}
                        style={{ bottom: `${(d.questions / max) * 100}%` }}
                      >
                        <span className="block text-sm font-semibold tabular-nums">
                          {d.questions} {d.questions === 1 ? "question" : "questions"}
                        </span>
                        {d.failed > 0 && <span className="block text-[11px] text-muted-foreground">{d.failed} failed</span>}
                        <span className="block text-[11px] text-muted-foreground">{shortDay(d.day)}</span>
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-2 flex gap-[2px] text-[11px] text-muted-foreground" aria-hidden="true">
              {data.map((d, i) => (
                <span key={d.day} className="flex-1 overflow-visible text-center whitespace-nowrap">
                  {i % labelEvery === 0 ? shortDay(d.day) : ""}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Panel({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border bg-card/60 p-5">
      <h3 className="font-medium">{title}</h3>
      {description && <p className="mb-4 text-sm text-muted-foreground">{description}</p>}
      {children}
    </section>
  )
}

/** Horizontal bars, one hue; the count is written beside each bar, so the bar is never the only signal. */
function ToolUsage({ tools }: { tools: Analytics["tools"] }) {
  if (tools.length === 0) return <p className="text-sm text-muted-foreground">Amber hasn&apos;t used any tools in this period.</p>
  const max = Math.max(...tools.map((t) => t.calls))
  return (
    <ul className="space-y-3">
      {tools.map((t) => (
        <li key={t.tool} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate" title={t.tool}>
            {humanizeTool(t.tool)}
          </span>
          <span className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
            <span className="block h-full rounded-full bg-chart-1" style={{ width: `${(t.calls / max) * 100}%` }} />
          </span>
          <span className="text-right text-xs whitespace-nowrap tabular-nums">
            <span className="font-medium">{t.calls.toLocaleString()}</span>
            <span className="text-muted-foreground"> · {formatDuration(t.median_ms === null ? null : Math.round(t.median_ms))}</span>
            {t.failed > 0 && (
              <span className="ml-2 inline-flex items-center gap-0.5 text-destructive">
                <CircleAlert className="size-3" aria-hidden /> {t.failed} failed
              </span>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}

function LibraryHealth({ library }: { library: Analytics["library"] }) {
  const { showTab } = useAdminNav()
  const items = [
    { label: "Ready", value: library.ready, icon: CircleCheck, className: "text-success" },
    { label: "Processing", value: library.processing, icon: Loader2, className: "text-info" },
    { label: "Failed", value: library.failed, icon: CircleAlert, className: "text-destructive" },
  ]
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        {items.map(({ label, value, icon: Icon, className }) => (
          <div key={label} className="rounded-xl border bg-card/60 px-3 py-2">
            <div className={cn("flex items-center gap-1 text-xs", className)}>
              <Icon className="size-3.5" aria-hidden /> {label}
            </div>
            <div className="text-xl font-semibold tabular-nums">{value.toLocaleString()}</div>
          </div>
        ))}
      </div>
      {library.recent_failures.length > 0 ? (
        <div>
          <h4 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Recent failures</h4>
          <ul className="divide-y divide-border/60 rounded-xl border">
            {library.recent_failures.map((f) => (
              <li key={f.id} className="px-3 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate font-medium">{f.title}</span>
                  <time className="ml-auto shrink-0 text-xs text-muted-foreground" title={exactTime(f.updated_at)}>
                    {timeAgo(f.updated_at)}
                  </time>
                </div>
                {f.message && <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{f.message}</div>}
              </li>
            ))}
          </ul>
          <Button variant="link" size="sm" className="mt-1 px-0" onClick={() => showTab("documents")}>
            Review in Documents
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {library.total === 0 ? "No documents have been added yet." : "Every document indexed successfully."}
        </p>
      )}
    </div>
  )
}

export function AnalyticsTab() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30)
  // The server renders with UTC; the browser's own zone takes over once it hydrates.
  const tz = useSyncExternalStore(noSubscription, timeZone, () => "UTC")
  const { data, error } = useAdminData<Analytics>(`/api/admin/analytics?days=${days}&tz=${encodeURIComponent(tz)}`)
  const current = data?.current
  const previous = data?.previous

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Chat activity for the last {days} days, compared with the {days} days before. Days follow your time zone ({tz}).
        </p>
        <ToggleGroup
          type="single"
          variant="outline"
          value={String(days)}
          onValueChange={(value) => value && setDays(Number(value) as (typeof RANGES)[number])}
          aria-label="Time range"
        >
          {RANGES.map((r) => (
            <ToggleGroupItem key={r} value={String(r)} className="px-3">
              {r} days
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          Couldn&apos;t load analytics: {error}
        </p>
      )}
      {!data && !error && (
        <p role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
          <Spinner /> Loading analytics…
        </p>
      )}

      {data && current && previous && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="People asking"
              value={current.people.toLocaleString()}
              delta={change(current.people, previous.people, (d) => d.toLocaleString(), true)}
            />
            <StatTile
              label="Questions"
              value={current.questions.toLocaleString()}
              note={current.awaiting_approval ? `${current.awaiting_approval} waiting for approval` : undefined}
              delta={change(current.questions, previous.questions, (d) => d.toLocaleString(), true)}
            />
            <StatTile
              label="Answered successfully"
              value={current.success_rate === null ? "—" : `${Math.round(current.success_rate * 100)}%`}
              note={current.failed ? `${current.failed} failed` : undefined}
              delta={change(
                current.success_rate === null ? null : Math.round(current.success_rate * 100),
                previous.success_rate === null ? null : Math.round(previous.success_rate * 100),
                (d) => `${d} pts`,
                true,
              )}
            />
            <StatTile
              label="Typical response time"
              value={current.median_ms === null ? "—" : formatDuration(Math.round(current.median_ms))}
              note={current.p95_ms === null ? undefined : `Slowest 5% took over ${formatDuration(Math.round(current.p95_ms))}`}
              delta={change(current.median_ms, previous.median_ms, (d) => formatDuration(Math.round(d)), false)}
            />
          </div>

          <QuestionsChart data={data.per_day} />

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Tools Amber used" description="How often each tool ran, with its typical time.">
              <ToolUsage tools={data.tools} />
            </Panel>
            <Panel title="Library health" description="Documents only appear in answers once they're ready.">
              <LibraryHealth library={data.library} />
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Most-used sources" description="Documents Amber found most often while answering.">
              {data.sources.length === 0 ? (
                <p className="text-sm text-muted-foreground">No answers used internal documents in this period.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr className="border-b">
                      <th className="py-1.5 font-medium">Document</th>
                      <th className="py-1.5 text-right font-medium">Answers</th>
                      <th className="py-1.5 text-right font-medium">People</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sources.map((s) => (
                      <tr key={s.document_id} className="border-b border-border/50 last:border-0">
                        <td className="max-w-[16rem] truncate py-1.5" title={s.title ?? undefined}>
                          {s.title || "Untitled document"}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">{s.answers}</td>
                        <td className="py-1.5 text-right tabular-nums">{s.people}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
            <Panel title="Most active people" description="Who asked Amber the most questions.">
              {data.people.length === 0 ? (
                <p className="text-sm text-muted-foreground">No one has asked a question in this period.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr className="border-b">
                      <th className="py-1.5 font-medium">Person</th>
                      <th className="py-1.5 text-right font-medium">Questions</th>
                      <th className="py-1.5 text-right font-medium">Last asked</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.people.map((p) => (
                      <tr key={p.id} className="border-b border-border/50 last:border-0">
                        <td className="max-w-[14rem] py-1.5">
                          <div className="truncate">{p.name || p.email}</div>
                          {p.name && <div className="truncate text-xs text-muted-foreground">{p.email}</div>}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {p.questions}
                          {p.failed > 0 && <span className="block text-xs text-muted-foreground">{p.failed} failed</span>}
                        </td>
                        <td className="py-1.5 text-right whitespace-nowrap text-muted-foreground">
                          {p.last_asked ? <time title={exactTime(p.last_asked)}>{timeAgo(p.last_asked)}</time> : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </div>
          {data.tools.length === 0 && data.current.questions === 0 && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Wrench className="size-3.5" aria-hidden /> Analytics are built from query traces, which start when people chat with Amber.
            </div>
          )}
        </>
      )}
    </div>
  )
}
