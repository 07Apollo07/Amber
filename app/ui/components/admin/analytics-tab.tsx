"use client"

import { useState } from "react"
import { Table2, TrendingDown, TrendingUp } from "lucide-react"

import { Button } from "@/components/ui/button"
import { analyticsSummary, queriesPerDay } from "@/lib/mock-data"
import { cn } from "@/lib/utils"

function StatTile({
  label,
  value,
  delta,
  trend,
}: {
  label: string
  value: string
  delta: string
  /** Whether the delta is good news; null when neutral. */
  trend: "good" | "bad" | null
}) {
  return (
    <div className="rounded-2xl border bg-card/60 p-5">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 text-3xl font-semibold tracking-tight">{value}</div>
      <div
        className={cn(
          "mt-1 flex items-center gap-1 text-xs",
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

const TICKS = [0, 40, 80, 120]
const MAX = TICKS[TICKS.length - 1]

/** Single-series column chart: one hue, no legend (the title names the series). */
function QueriesChart() {
  const [hover, setHover] = useState<number | null>(null)
  const [showTable, setShowTable] = useState(false)
  const total = queriesPerDay.reduce((sum, d) => sum + d.count, 0)

  return (
    <div className="rounded-2xl border bg-card/60 p-5">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium">Queries per day</h3>
          <p className="text-sm text-muted-foreground">Last 14 days · {total.toLocaleString()} total</p>
        </div>
        <Button variant="ghost" size="sm" aria-pressed={showTable} onClick={() => setShowTable((s) => !s)}>
          <Table2 /> {showTable ? "Show chart" : "Show table"}
        </Button>
      </div>

      {showTable ? (
        <table className="w-full text-sm">
          <caption className="sr-only">Queries per day</caption>
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="py-1.5 font-medium">Day</th>
              <th className="py-1.5 text-right font-medium">Queries</th>
            </tr>
          </thead>
          <tbody>
            {queriesPerDay.map((d) => (
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
            {TICKS.map((t) => (
              <span key={t} className="absolute right-0 -translate-y-1/2" style={{ bottom: `calc(${(t / MAX) * 100}% - 0px)` }}>
                {t}
              </span>
            ))}
          </div>
          <div className="min-w-0 flex-1">
            <div className="relative h-48">
              {TICKS.map((t) => (
                <div
                  key={t}
                  className="absolute inset-x-0 border-t border-border/70"
                  style={{ bottom: `${(t / MAX) * 100}%` }}
                  aria-hidden="true"
                />
              ))}
              <div className="absolute inset-0 flex items-end gap-[2px]">
                {queriesPerDay.map((d, i) => (
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
                      className={cn(
                        "block w-full max-w-6 rounded-t-[4px] bg-chart-1 transition-[filter]",
                        hover === i && "brightness-125",
                      )}
                      style={{ height: `${(d.count / MAX) * 100}%` }}
                    />
                    {hover === i && (
                      <span className="pointer-events-none absolute z-10 -translate-y-2 rounded-lg border bg-popover px-2.5 py-1.5 text-left whitespace-nowrap shadow-lg" style={{ bottom: `${(d.count / MAX) * 100}%` }}>
                        <span className="block text-sm font-semibold tabular-nums">{d.count}</span>
                        <span className="block text-[11px] text-muted-foreground">{d.day}</span>
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-2 flex gap-[2px] text-[11px] text-muted-foreground" aria-hidden="true">
              {queriesPerDay.map((d, i) => (
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
  const s = analyticsSummary
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Active users (7 days)" value={s.activeUsers.toLocaleString()} delta={s.activeUsersDelta} trend="good" />
        <StatTile label="Queries this week" value={s.queriesThisWeek.toLocaleString()} delta={s.queriesDelta} trend="good" />
        <StatTile label="Answers rated helpful" value={`${Math.round(s.helpfulRate * 100)}%`} delta={s.helpfulDelta} trend="good" />
        <StatTile label="Ingestion failures" value={s.ingestionFailures.toLocaleString()} delta={s.ingestionDelta} trend={null} />
      </div>
      <QueriesChart />
    </div>
  )
}
