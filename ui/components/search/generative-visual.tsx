"use client"

import { useMemo, useState } from "react"
import { ArrowDownRight, ArrowUpRight, FileText, Minus } from "lucide-react"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"

type Scalar = string | number | boolean | null
type DataRow = Record<string, Scalar>

export type GenerativeVisual = {
  id: string
  kind: "chart" | "table" | "metrics" | "comparison" | "timeline" | "sources"
  title: string
  description: string
  chart_type?: "bar" | "line" | "area" | "donut"
  category_key?: string
  series?: string[]
  columns?: string[]
  rows?: DataRow[]
  metrics?: { label: string; value: Scalar; change?: string; detail?: string; trend?: "up" | "down" | "neutral" }[]
  events?: { date: string; event: string; details: string }[]
  sources?: { title: string; excerpt: string; url?: string }[]
}

const chartColors = [
  "var(--color-primary)",
  "var(--color-chart-2, #0ea5e9)",
  "var(--color-chart-3, #a855f7)",
  "var(--color-chart-4, #f59e0b)",
  "var(--color-chart-5, #10b981)",
  "var(--color-chart-6, #ef4444)",
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isScalar(value: unknown): value is Scalar {
  return value === null || ["string", "number", "boolean"].includes(typeof value)
}

export function isGenerativeVisual(value: unknown): value is GenerativeVisual {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.title !== "string" ||
    typeof value.description !== "string" ||
    !["chart", "table", "metrics", "comparison", "timeline", "sources"].includes(String(value.kind))
  ) {
    return false
  }

  if (value.kind === "chart") {
    return (
      ["bar", "line", "area", "donut"].includes(String(value.chart_type)) &&
      typeof value.category_key === "string" &&
      Array.isArray(value.series) &&
      value.series.every((series) => typeof series === "string") &&
      Array.isArray(value.rows) &&
      value.rows.every((row) => isRecord(row) && Object.values(row).every(isScalar))
    )
  }
  if (value.kind === "table" || value.kind === "comparison") {
    return (
      Array.isArray(value.columns) &&
      value.columns.every((column) => typeof column === "string") &&
      Array.isArray(value.rows) &&
      value.rows.every((row) => isRecord(row) && Object.values(row).every(isScalar))
    )
  }
  if (value.kind === "metrics") {
    return (
      Array.isArray(value.metrics) &&
      value.metrics.every(
        (metric) =>
          isRecord(metric) &&
          typeof metric.label === "string" &&
          isScalar(metric.value) &&
          (metric.change === undefined || typeof metric.change === "string") &&
          (metric.detail === undefined || typeof metric.detail === "string") &&
          (metric.trend === undefined || ["up", "down", "neutral"].includes(String(metric.trend))),
      )
    )
  }
  if (value.kind === "timeline") {
    return (
      Array.isArray(value.events) &&
      value.events.every(
        (event) =>
          isRecord(event) &&
          typeof event.date === "string" &&
          typeof event.event === "string" &&
          typeof event.details === "string",
      )
    )
  }
  return (
    Array.isArray(value.sources) &&
    value.sources.every(
      (source) =>
        isRecord(source) &&
        typeof source.title === "string" &&
        typeof source.excerpt === "string" &&
        (source.url === undefined ||
          (typeof source.url === "string" && isWorkspaceUrl(source.url))),
    )
  )
}

function isWorkspaceUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === "https:" && ["drive.google.com", "docs.google.com"].includes(url.hostname)
  } catch {
    return false
  }
}

function displayValue(value: Scalar | undefined): string {
  if (value === null || value === undefined || value === "") return "—"
  return typeof value === "number"
    ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)
    : String(value)
}

function Chart({ visual }: { visual: GenerativeVisual }) {
  const [chartType, setChartType] = useState(visual.chart_type || "bar")
  const [visibleSeries, setVisibleSeries] = useState<string[]>(visual.series || [])
  const rows = visual.rows || []
  const series = visual.series || []
  const categoryKey = visual.category_key || ""
  const [visibleCategories, setVisibleCategories] = useState(
    rows.map((row) => displayValue(row[categoryKey])),
  )
  const values = rows.map((row) => visibleSeries.map((key) => Number(row[key]) || 0))
  const maxValue = Math.max(1, ...values.flat())
  const chartRows = rows.slice(0, 24)

  function toggleSeries(key: string) {
    setVisibleSeries((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    )
  }

  function toggleCategory(category: string) {
    setVisibleCategories((current) =>
      current.includes(category) ? current.filter((item) => item !== category) : [...current, category],
    )
  }

  const points = useMemo(
    () => chartRows.map((row) => displayValue(row[categoryKey])),
    [chartRows, categoryKey],
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1" aria-label="Chart type">
          {(["bar", "line", "area", ...(series.length === 1 ? ["donut" as const] : [])] as const).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => setChartType(type)}
              aria-pressed={chartType === type}
              className={cn(
                "rounded-md border px-2 py-1 text-xs capitalize transition-colors",
                chartType === type ? "border-primary bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted",
              )}
            >
              {type}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {series.map((key, index) => (
            <button
              key={key}
              type="button"
              onClick={() => toggleSeries(key)}
              aria-pressed={visibleSeries.includes(key)}
              className={cn(
                "inline-flex items-center gap-1.5 text-xs",
                !visibleSeries.includes(key) && "opacity-40",
              )}
            >
              <span className="size-2 rounded-full" style={{ backgroundColor: chartColors[index % chartColors.length] }} />
              {key}
            </button>
          ))}
        </div>
      </div>
      <div className="grid min-w-0 grid-cols-[auto_1fr] gap-2">
        {chartType !== "donut" && (
          <div className="flex h-48 flex-col justify-between pb-6 text-right text-[10px] text-muted-foreground">
            {[1, 0.66, 0.33, 0].map((fraction) => (
              <span key={fraction}>{displayValue(Math.round(maxValue * fraction))}</span>
            ))}
          </div>
        )}
        <div className="relative min-w-0">
          <svg
            viewBox={chartType === "donut" ? "0 0 240 200" : "0 0 600 190"}
            preserveAspectRatio="none"
            role="img"
            aria-label={`${chartType} chart for ${visual.title}`}
            className={cn(
              "h-48 w-full overflow-visible",
              chartType === "donut" && "col-span-2 mx-auto max-w-64",
            )}
          >
            {chartType !== "donut" && [0, 1, 2, 3].map((line) => (
              <line key={line} x1="0" x2="600" y1={line * 48 + 4} y2={line * 48 + 4} stroke="currentColor" className="text-border" strokeDasharray="3 5" />
            ))}
            {chartType === "donut" && (() => {
              const donutRows = chartRows.filter((row) => visibleCategories.includes(displayValue(row[categoryKey])))
              const total = donutRows.reduce((sum, row) => sum + Math.max(0, Number(row[series[0]]) || 0), 0)
              const circumference = 2 * Math.PI * 64
              let offset = 0
              return (
                <g>
                  {donutRows.map((row, index) => {
                    const value = Math.max(0, Number(row[series[0]]) || 0)
                    const segment = total ? (value / total) * circumference : 0
                    const circle = (
                      <circle
                        key={`${displayValue(row[categoryKey])}-${index}`}
                        cx="120"
                        cy="95"
                        r="64"
                        fill="none"
                        stroke={chartColors[index % chartColors.length]}
                        strokeWidth="28"
                        strokeDasharray={`${segment} ${circumference - segment}`}
                        strokeDashoffset={-offset}
                        transform="rotate(-90 120 95)"
                      >
                        <title>{`${displayValue(row[categoryKey])}: ${displayValue(value)}`}</title>
                      </circle>
                    )
                    offset += segment
                    return circle
                  })}
                  <circle cx="120" cy="95" r="46" fill="var(--color-card)" />
                  <text x="120" y="91" textAnchor="middle" className="fill-foreground text-[11px]">{series[0]}</text>
                  <text x="120" y="108" textAnchor="middle" className="fill-muted-foreground text-[10px]">{displayValue(total)}</text>
                </g>
              )
            })()}
            {chartType === "bar" &&
              chartRows.map((row, rowIndex) => {
                const groupWidth = 560 / chartRows.length
                const barWidth = Math.max(2, (groupWidth * 0.72) / Math.max(1, visibleSeries.length))
                return visibleSeries.map((key) => {
                  const seriesIndex = series.indexOf(key)
                  const value = Number(row[key]) || 0
                  const height = (value / maxValue) * 160
                  const x = 20 + rowIndex * groupWidth + (groupWidth - barWidth * visibleSeries.length) / 2 + visibleSeries.indexOf(key) * barWidth
                  return (
                    <rect
                      key={`${rowIndex}-${key}`}
                      x={x}
                      y={168 - height}
                      width={barWidth}
                      height={height}
                      rx="2"
                      fill={chartColors[seriesIndex % chartColors.length]}
                    >
                      <title>{`${displayValue(row[categoryKey])}: ${key} ${displayValue(value)}`}</title>
                    </rect>
                  )
                })
              })}
            {(chartType === "line" || chartType === "area") &&
              visibleSeries.map((key) => {
                const seriesIndex = series.indexOf(key)
                const coords = chartRows
                  .map((row, rowIndex) => {
                    const x = chartRows.length === 1 ? 300 : 20 + (rowIndex * 560) / (chartRows.length - 1)
                    const y = 168 - ((Number(row[key]) || 0) / maxValue) * 160
                    return `${x},${y}`
                  })
                  .join(" ")
                const areaCoords = `20,168 ${coords} 580,168`
                return (
                  <g key={key}>
                    {chartType === "area" && (
                      <polygon points={areaCoords} fill={chartColors[seriesIndex % chartColors.length]} opacity="0.12" />
                    )}
                    <polyline
                      points={coords}
                      fill="none"
                      stroke={chartColors[seriesIndex % chartColors.length]}
                      strokeWidth="3"
                      strokeLinejoin="round"
                      strokeLinecap="round"
                    />
                    {chartRows.map((row, rowIndex) => {
                      const x = chartRows.length === 1 ? 300 : 20 + (rowIndex * 560) / (chartRows.length - 1)
                      const y = 168 - ((Number(row[key]) || 0) / maxValue) * 160
                      return (
                        <circle key={`${key}-${rowIndex}`} cx={x} cy={y} r="4" fill={chartColors[seriesIndex % chartColors.length]}>
                          <title>{`${displayValue(row[categoryKey])}: ${key} ${displayValue(row[key])}`}</title>
                        </circle>
                      )
                    })}
                  </g>
                )
              })}
          </svg>
          {chartType !== "donut" && <div className="grid grid-cols-6 gap-1 text-center text-[10px] text-muted-foreground">
            {points.map((point, index) => (
              <span key={`${point}-${index}`} className="truncate">{point}</span>
            ))}
          </div>}
        </div>
      </div>
      {chartType === "donut" && (
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {chartRows.map((row, index) => {
            const category = displayValue(row[categoryKey])
            return (
              <button
                key={`${category}-${index}`}
                type="button"
                onClick={() => toggleCategory(category)}
                aria-pressed={visibleCategories.includes(category)}
                className={cn("inline-flex items-center gap-1.5 text-xs", !visibleCategories.includes(category) && "opacity-40")}
              >
                <span className="size-2 rounded-full" style={{ backgroundColor: chartColors[index % chartColors.length] }} />
                {category}
              </button>
            )
          })}
        </div>
      )}
      {rows.length > chartRows.length && (
        <p className="text-xs text-muted-foreground">Showing the first {chartRows.length} of {rows.length} data points.</p>
      )}
    </div>
  )
}

function DataTable({ visual, comparison = false }: { visual: GenerativeVisual; comparison?: boolean }) {
  const [query, setQuery] = useState("")
  const columns = visual.columns || []
  const rows = (visual.rows || []).filter((row) =>
    columns.some((column) => displayValue(row[column]).toLowerCase().includes(query.toLowerCase())),
  )
  return (
    <div className="space-y-2">
      {visual.rows && visual.rows.length > 8 && (
        <input
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder="Filter rows…"
          aria-label={`Filter ${visual.title}`}
          className="h-8 w-full rounded-md border bg-background px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      )}
      <div className="max-h-80 overflow-auto rounded-md border">
        <table className={cn("w-full border-collapse text-left text-xs", comparison && "min-w-[480px]")}>
          <thead className="sticky top-0 bg-muted">
            <tr>{columns.map((column) => <th key={column} className="px-3 py-2 font-medium">{column}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} className="border-t">
                {columns.map((column) => (
                  <td key={column} className="max-w-64 whitespace-pre-wrap px-3 py-2 align-top">{displayValue(row[column])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="p-3 text-xs text-muted-foreground">No rows match this filter.</p>}
      </div>
    </div>
  )
}

export function GenerativeVisualCard({ visual }: { visual: GenerativeVisual }) {
  return (
    <Card className="my-2 w-full max-w-3xl gap-3 border bg-card py-0 shadow-sm">
      <CardHeader className="border-b py-3">
        <CardTitle>{visual.title}</CardTitle>
        {visual.description && <CardDescription>{visual.description}</CardDescription>}
      </CardHeader>
      <CardContent className="pb-4">
        {visual.kind === "chart" && <Chart visual={visual} />}
        {(visual.kind === "table" || visual.kind === "comparison") && (
          <DataTable visual={visual} comparison={visual.kind === "comparison"} />
        )}
        {visual.kind === "metrics" && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(visual.metrics || []).map((metric) => {
              const TrendIcon = metric.trend === "up" ? ArrowUpRight : metric.trend === "down" ? ArrowDownRight : Minus
              return (
                <div key={metric.label} className="rounded-lg border bg-background p-3">
                  <div className="text-xs text-muted-foreground">{metric.label}</div>
                  <div className="mt-1 text-2xl font-semibold tracking-tight">{displayValue(metric.value)}</div>
                  {(metric.change || metric.detail) && (
                    <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                      {metric.change && <TrendIcon className={cn("size-3.5", metric.trend === "up" && "text-emerald-600", metric.trend === "down" && "text-destructive")} />}
                      {metric.change || metric.detail}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
        {visual.kind === "timeline" && (
          <ol className="space-y-0">
            {(visual.events || []).map((event, index) => (
              <li key={`${event.date}-${index}`} className="relative grid grid-cols-[100px_16px_1fr] gap-2 pb-4 last:pb-0">
                <span className="pt-0.5 text-right text-xs text-muted-foreground">{event.date}</span>
                <span className="relative flex justify-center">
                  <span className="mt-1 size-2.5 rounded-full border-2 border-primary bg-background" />
                  {index < (visual.events || []).length - 1 && <span className="absolute top-3 h-full w-px bg-border" />}
                </span>
                <span>
                  <span className="text-sm font-medium">{event.event}</span>
                  {event.details && <span className="mt-0.5 block text-xs text-muted-foreground">{event.details}</span>}
                </span>
              </li>
            ))}
          </ol>
        )}
        {visual.kind === "sources" && (
          <div className="space-y-2">
            {(visual.sources || []).map((source, index) => (
              <div key={`${source.title}-${index}`} className="rounded-lg border bg-background p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <FileText className="size-4 shrink-0 text-primary" />
                  {source.url && isWorkspaceUrl(source.url) ? (
                    <a href={source.url} target="_blank" rel="noreferrer" className="underline-offset-4 hover:underline">{source.title}</a>
                  ) : source.title}
                </div>
                <p className="mt-1 line-clamp-4 text-xs leading-relaxed text-muted-foreground">{source.excerpt}</p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
