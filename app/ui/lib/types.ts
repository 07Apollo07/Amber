// UI-side shapes for Phase 1. These mirror the planned API contract and will be
// replaced by types generated from packages/api-contract once the backend exists.

export type Role = "admin" | "member"

export type User = {
  id: string
  name: string
  email: string
  domain: string | null
  role: Role
  status: "active" | "deactivated"
  lastActive: string
  documentCount: number
}

export type FileType = "pdf" | "docx" | "pptx" | "xlsx" | "txt" | "md" | "gdoc" | "gsheet" | "gslides"

export type DocumentOrigin = "desktop_upload" | "drive_picker"

export type IngestionStatus =
  | "queued"
  | "saving_to_drive"
  | "parsing"
  | "embedding"
  | "ready"
  | "failed"

export type Sharing =
  | { kind: "private" }
  | { kind: "people"; emails: string[] }
  | { kind: "domain"; domain: string }

export type AmberDocument = {
  id: string
  title: string
  fileType: FileType
  origin: DocumentOrigin
  owner: string
  collection: string | null
  tags: string[]
  sharing: Sharing
  status: IngestionStatus
  error?: string
  sizeBytes: number
  pages: number
  updatedAt: string
  driveUrl: string | null
}

export type Source = {
  n: number
  documentId: string
  title: string
  fileType: FileType
  origin: DocumentOrigin
  page: number
  snippet: string
  /** The exact sentence the answer cites, highlighted inside the snippet. */
  citedSpan: string
  updatedAt: string
  driveUrl: string
}

export type TraceChunk = {
  documentTitle: string
  page: number
  vectorScore: number
  keywordScore: number
  rerankScore: number
  cited: boolean
}

export type Trace = {
  id: string
  query: string
  rewrittenQuery: string
  chunks: TraceChunk[]
  hiddenCount: number
  model: string
  latencyMs: number
  promptTokens: number
  completionTokens: number
}

export type Answer = {
  markdown: string
  sources: Source[]
  trace: Trace
}

export type ChatMessage =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; answer: Answer }

export type Conversation = {
  id: string
  title: string
  updatedAt: string
}

export type AuditEvent = {
  id: string
  at: string
  actor: string
  action: string
  target: string
  detail: string
}

export type UploadRow = {
  id: string
  name: string
  sizeBytes: number
  status: IngestionStatus
  progress: number
  error?: string
  driveUrl: string | null
}

export type SearchHistoryItem = {
  id: string
  query: string
  at: string
}

export type QueryTraceRow = Trace & {
  user: string
  at: string
  feedback: "up" | "down" | null
}

/** The signed-in user, as returned by GET /api/me. */
export type SessionUser = {
  id: string
  email: string
  name: string
  picture: string | null
  domain: string | null
  role: Role
  drive: { connected: boolean; scopes: string[] }
}
