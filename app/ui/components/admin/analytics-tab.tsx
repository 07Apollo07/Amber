"use client"

import { useState } from "react"
import { BarChart3, Table2, TrendingDown, TrendingUp } from "lucide-react"

import { EmptyState } from "@/components/app/empty-state"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type DayCount = { day: string; count: number }

type Summary = {
  activeUsers: number
  queriesThisWeek: number
  helpfulRate: number
  ingestionFailures: number
}

// Loaded from the analytics API once it exists.
const summary: Summary | null = null
const queriesPerDay: DayCount[] = []

function StatTile({
  label,
  value,
  delta,
  trend = null,
}: {
  label: string
  value: string
  delta?: string
  /** Whether the delta is good news; null when neutral. */
  trend?: "good" | "bad" | null
}) {
  return (
    <div className="rounded-2xl border bg-card/60 p-5">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 text-3xl font-semibold tracking-tight">{value}</div>
      <div
        className={cn(
          "mt-1 flex min-h-4 items-center gap-1 text-xs",
          trend === "good" && "text-success",
          trend === "bad" && "text-destructive",
          trend === null && "text-muted-foreground",
        )}
      >
        {trend === "good" && <TrendingUp className="size-3.5" />}
        {trend === "bad" && <TrendingDown className="size-3.5" />}
        {delta}
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
function QueriesChart({ data }: { data: DayCount[] }) {
  const [hover, setHover] = useState<number | null>(null)
  const [showTable, setShowTable] = useState(false)
  const total = data.reduce((sum, d) => sum + d.count, 0)
  const ticks = niceTicks(Math.max(0, ...data.map((d) => d.count)))
  const max = ticks[ticks.length - 1]

  return (
    <div className="rounded-2xl border bg-card/60 p-5">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium">Queries per day</h3>
          <p className="text-sm text-muted-foreground">
            {data.length ? `Last ${data.length} days · ${total.toLocaleString()} total` : "Last 14 days"}
          </p>
        </div>
        {data.length > 0 && (
          <Button variant="ghost" size="sm" aria-pressed={showTable} onClick={() => setShowTable((s) => !s)}>
            <Table2 /> {showTable ? "Show chart" : "Show table"}
          </Button>
        )}
      </div>

      {data.length === 0 ? (
        <EmptyState icon={BarChart3} title="No queries yet" description="Daily query counts will appear once people start searching." />
      ) : showTable ? (
        <table className="w-full text-sm">
          <caption className="sr-only">Queries per day</caption>
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="py-1.5 font-medium">Day</th>
              <th className="py-1.5 text-right font-medium">Queries</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.day} className="border-b border-border/50 last:border-0">
                <td className="py-1.5">{d.day}</td>
                <td className="py-1.5 text-right tabular-nums">{d.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="mt-6 flex gap-2" role="group" aria-label={`Queries per day, ${total} in total. Each column is a button showing its value.`}>
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
                <div key={t} className="absolute inset-x-0 border-t border-border/70" style={{ bottom: `${(t / max) * 100}%` }} aria-hidden="true" />
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
                    aria-label={`${d.day}: ${d.count} queries`}
                  >
                    <span
                      className={cn("block w-full max-w-6 rounded-t-[4px] bg-chart-1 transition-[filter]", hover === i && "brightness-125")}
                      style={{ height: `${(d.count / max) * 100}%` }}
                    />
                    {hover === i && (
                      <span
                        className="pointer-events-none absolute z-10 -translate-y-2 rounded-lg border bg-popover px-2.5 py-1.5 text-left whitespace-nowrap shadow-lg"
                        style={{ bottom: `${(d.count / max) * 100}%` }}
                      >
                        <span className="block text-sm font-semibold tabular-nums">{d.count}</span>
                        <span className="block text-[11px] text-muted-foreground">{d.day}</span>
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-2 flex gap-[2px] text-[11px] text-muted-foreground" aria-hidden="true">
              {data.map((d, i) => (
                <span key={d.day} className="flex-1 text-center whitespace-nowrap">
                  {i % 4 === 0 ? d.day : ""}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function AnalyticsTab() {
  const s: Summary | null = summary
  const empty = "—"
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Active users (7 days)" value={s ? s.activeUsers.toLocaleString() : empty} />
        <StatTile label="Queries this week" value={s ? s.queriesThisWeek.toLocaleString() : empty} />
        <StatTile label="Answers rated helpful" value={s ? `${Math.round(s.helpfulRate * 100)}%` : empty} />
        <StatTile label="Ingestion failures" value={s ? s.ingestionFailures.toLocaleString() : empty} />
      </div>
      <QueriesChart data={queriesPerDay} />
    </div>
  )
}
