/** Plain-English wording for the admin audit log and query traces. */

export type AuditCategory = "sign_in" | "chat" | "documents" | "collections" | "sharing" | "drive" | "admin" | "other"

export type AuditEvent = {
  id: string
  at: string
  actor: { id: string | null; email: string | null; name: string | null }
  action: string
  category: AuditCategory
  target: string | null
  target_label: string | null
  target_kind: "conversation" | "collection" | "document" | null
  detail: Record<string, unknown>
  ip: string | null
}

export type TraceStatus = "completed" | "failed" | "awaiting_approval"

export type TraceSource = {
  document_id?: string
  title?: string
  file_type?: string
  page?: number
  origin?: string
  vector_distance?: number
  text_rank?: number
}

export type TraceStep =
  | {
      type: "model"
      at_ms: number
      duration_ms: number
      decision: "tools" | "answer"
      prompt_tokens: number | null
      completion_tokens: number | null
    }
  | {
      type: "tool"
      tool: string
      input: Record<string, unknown>
      status: "running" | "completed" | "failed" | "stopped"
      at_ms?: number
      duration_ms: number | null
      result_chars?: number
      error?: string
      sources?: TraceSource[]
    }

export type TraceSummary = {
  id: string
  at: string
  user: { id: string; email: string; name: string | null }
  conversation_id: string | null
  question: string
  kind: "chat" | "approval"
  status: TraceStatus
  model: string | null
  latency_ms: number
  tokens: number | null
  tools: string[]
  tool_calls: number
  failed_tools: number
  source_count: number
  error: string | null
}

export type TraceDetail = TraceSummary & {
  prompt_tokens: number | null
  completion_tokens: number | null
  steps: TraceStep[]
}

export const categoryLabel: Record<AuditCategory, string> = {
  sign_in: "Sign-in",
  chat: "Chat",
  documents: "Documents",
  collections: "Collections",
  sharing: "Sharing",
  drive: "Drive",
  admin: "Admin",
  other: "Other",
}

export const traceStatusLabel: Record<TraceStatus, string> = {
  completed: "Answered",
  failed: "Failed",
  awaiting_approval: "Waiting for approval",
}

export function personName(actor: { name: string | null; email: string | null }): string {
  return actor.name?.trim() || actor.email || "Someone"
}

/** "leave_policy.pdf" → "leave policy.pdf"; "drive_get_file" → "Drive get file". */
export function humanize(code: string): string {
  const words = code.replace(/[._]+/g, " ").trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function quoted(value: unknown): string {
  return typeof value === "string" && value ? `“${value}”` : ""
}

function count(n: unknown, one: string, many = `${one}s`): string {
  const value = typeof n === "number" ? n : Number(n)
  return Number.isFinite(value) ? `${value} ${value === 1 ? one : many}` : many
}

/** The rest of a sentence that starts with the person's name, e.g. "signed in". */
export function describeAuditEvent(event: AuditEvent): string {
  const d = event.detail
  const name = event.target_label ? quoted(event.target_label) : ""
  switch (event.action) {
    case "auth.login":
      return d.drive_connected ? "signed in (Google Drive connected)" : "signed in"
    case "auth.logout":
      return "signed out"
    case "auth.logout_all":
      return "signed out on every device"
    case "auth.login_blocked":
      return "was blocked from signing in because the account is deactivated"
    case "agent.chat_message": {
      const where = name ? ` in ${name}` : ""
      if (d.status === "failed") return `asked Amber a question${where}, which failed`
      if (d.status === "awaiting_approval") return `asked Amber to make a change${where}, which needs approval`
      return `asked Amber a question${where}`
    }
    case "agent.approval":
      return `${d.decision === "approve" ? "approved" : "rejected"} ${quoted(d.title) || "a workspace change"}`
    case "agent.conversation_renamed":
      return `renamed a conversation to ${quoted(d.title)}`
    case "agent.conversation_deleted":
      return `deleted the conversation ${quoted(d.title) || ""}`.trim()
    case "agent.live_session":
      return "started an Opal voice session"
    case "upload_document":
      return `uploaded ${quoted(event.target) || "a document"}`
    case "delete_document":
      return `deleted ${name || "a document"}`
    case "import_drive_files":
      return `imported ${count(d.imported_count, "file")} from Google Drive${Number(d.failed_count) ? ` (${d.failed_count} failed)` : ""}`
    case "update_document_access":
      return `changed who can open ${name || "a document"}`
    case "share_collection":
      return `changed sharing on the collection ${quoted(d.name) || name}`.trim()
    case "organize_collection_document":
      return `${d.included === false ? "removed a document from" : "added a document to"} ${name ? `the collection ${name}` : "a collection"}`
    case "delete_collection":
      return `deleted the collection ${quoted(d.name) || name}`.trim()
    case "create_collection":
      return `created the collection ${quoted(d.name) || name}`.trim()
    case "drive.disconnect":
      return "disconnected Google Drive"
    case "admin.add_user":
      return `added ${event.target ?? "a user"} as ${d.role === "admin" ? "an admin" : "a member"}`
    case "admin.update_user":
      return `changed ${event.target ?? "a user"} to ${d.status === "deactivated" ? "deactivated" : String(d.role ?? "")}`
    case "admin.delete_user":
      return `deleted the account ${event.target ?? ""}`.trim()
    case "admin.update_settings":
      return `changed the ${SETTINGS_SECTION[event.target ?? ""] ?? "app"} settings`
    case "admin.audit_export":
      return `exported ${count(d.rows, "audit event")}`
    default:
      return humanize(event.action).toLowerCase()
  }
}

const SETTINGS_SECTION: Record<string, string> = { indexing: "indexing", chat: "chat", voice: "Opal voice" }

const HIDDEN_DETAIL_KEYS = new Set(["trace_id", "operation_id"])

/** Detail fields as readable label/value pairs. */
export function detailRows(event: AuditEvent): { label: string; value: string }[] {
  if (event.action === "admin.update_settings") return settingsChanges(event)
  const rows: { label: string; value: string }[] = []
  for (const [key, value] of Object.entries(event.detail)) {
    if (HIDDEN_DETAIL_KEYS.has(key) || value === null || value === undefined || value === "") continue
    rows.push({ label: humanize(key), value: formatValue(value) })
  }
  if (event.target && event.target_label) rows.unshift({ label: "ID", value: event.target })
  else if (event.target && event.action !== "upload_document") rows.unshift({ label: "Target", value: event.target })
  if (event.ip) rows.push({ label: "IP address", value: event.ip })
  return rows
}

/** "Passages per search: 5 → 8", only for the fields that changed. */
function settingsChanges(event: AuditEvent): { label: string; value: string }[] {
  const from = (event.detail.from ?? {}) as Record<string, unknown>
  const to = (event.detail.to ?? {}) as Record<string, unknown>
  const rows = Object.keys({ ...from, ...to })
    .filter((key) => JSON.stringify(from[key]) !== JSON.stringify(to[key]))
    .map((key) => ({ label: humanize(key), value: `${settingValue(from[key])} → ${settingValue(to[key])}` }))
  return rows.length ? rows : [{ label: "Change", value: "Saved without changes" }]
}

function settingValue(value: unknown): string {
  if (value === null || value === undefined) return "Server default"
  if (typeof value === "boolean") return value ? "On" : "Off"
  return String(value)
}

function formatValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "Yes" : "No"
  if (Array.isArray(value)) return value.length ? value.map((v) => (typeof v === "string" ? humanizeTool(v) : formatValue(v))).join(", ") : "None"
  if (typeof value === "object" && value !== null) {
    return Object.entries(value)
      .map(([k, v]) => `${humanize(k)}: ${formatValue(v)}`)
      .join(" · ")
  }
  return String(value)
}

const TOOL_NAMES: Record<string, string> = {
  vector_search: "Document search",
  web_search: "Web search",
  get_file: "Read document",
  drive_search_files: "Drive search",
  drive_get_file: "Open Drive file",
  drive_list_permissions: "List sharing",
  drive_list_comments: "List comments",
  read_google_doc: "Read Google Doc",
  read_google_sheet: "Read Google Sheet",
  update_task_list: "Task list",
  render_chart: "Chart",
  render_table: "Table",
  render_metric_cards: "Metric cards",
  render_comparison: "Comparison",
  render_timeline: "Timeline",
  render_source_cards: "Source cards",
}

export function humanizeTool(tool: string): string {
  return TOOL_NAMES[tool] ?? humanize(tool)
}

function input(step: Extract<TraceStep, { type: "tool" }>, key: string): string {
  const value = step.input[key]
  return typeof value === "string" ? value : ""
}

/** One readable line for a tool call, e.g. Searched your documents for “leave policy”. */
export function describeToolStep(step: Extract<TraceStep, { type: "tool" }>): string {
  const q = quoted(input(step, "query"))
  switch (step.tool) {
    case "vector_search":
      return `Searched internal documents for ${q || "something"}`
    case "web_search":
      return `Searched the web for ${q || "something"}`
    case "drive_search_files": {
      const term = quoted(input(step, "name_contains") || input(step, "full_text_contains"))
      return term ? `Searched Drive for ${term}` : "Listed Drive files"
    }
    case "get_file":
      return "Read a full indexed document"
    case "drive_get_file":
      return "Opened a Drive file"
    case "drive_list_permissions":
      return "Checked who a Drive file is shared with"
    case "drive_list_comments":
      return "Read a Drive file's comments"
    case "read_google_doc":
      return "Read a Google Doc"
    case "read_google_sheet":
      return input(step, "ranges") ? `Read ${input(step, "ranges")} of a Google Sheet` : "Read a Google Sheet"
    case "update_task_list":
      return "Updated the task list"
    case "render_chart":
      return `Drew a chart${input(step, "title") ? ` (${quoted(input(step, "title"))})` : ""}`
    case "render_table":
    case "render_metric_cards":
    case "render_comparison":
    case "render_timeline":
    case "render_source_cards":
      return `Showed ${humanizeTool(step.tool).toLowerCase()}`
    default:
      return `Ran ${humanizeTool(step.tool)}`
  }
}

/** The inputs a tool sentence doesn't already mention. */
export function extraInputs(step: Extract<TraceStep, { type: "tool" }>): { label: string; value: string }[] {
  const shown = new Set(["query"])
  if (step.tool === "read_google_sheet") shown.add("ranges")
  if (step.tool === "drive_search_files") shown.add(step.input.name_contains ? "name_contains" : "full_text_contains")
  if (step.tool === "render_chart") shown.add("title")
  return Object.entries(step.input)
    .filter(([key, value]) => !shown.has(key) && value !== null && value !== "")
    .map(([key, value]) => ({ label: humanize(key), value: formatValue(value) }))
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—"
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const minutes = Math.floor(ms / 60_000)
  return `${minutes} min ${Math.round((ms % 60_000) / 1000)} s`
}

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" })

export function timeAgo(iso: string, now = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const abs = Math.abs(seconds)
  if (abs < 45) return "just now"
  if (abs < 3600) return relative.format(Math.round(seconds / 60), "minute")
  if (abs < 86_400) return relative.format(Math.round(seconds / 3600), "hour")
  if (abs < 7 * 86_400) return relative.format(Math.round(seconds / 86_400), "day")
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })
}

export function exactTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "full", timeStyle: "medium" })
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
}

/** "Today", "Yesterday" or a full date, for grouping rows by day. */
export function dayLabel(iso: string, now = new Date()): string {
  const day = new Date(iso)
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startOfDay = new Date(day.getFullYear(), day.getMonth(), day.getDate()).getTime()
  const diffDays = Math.round((startOfToday - startOfDay) / 86_400_000)
  if (diffDays === 0) return "Today"
  if (diffDays === 1) return "Yesterday"
  return day.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })
}

/** Cosine distance → a 0–100 "match" score for display. */
export function matchPercent(source: TraceSource): number | null {
  if (typeof source.vector_distance !== "number") return null
  return Math.max(0, Math.min(100, Math.round((1 - source.vector_distance) * 100)))
}
