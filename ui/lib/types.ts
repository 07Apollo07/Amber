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

export type ToolCallTrace = {
  id: string
  name: string
  args: string
  result?: string
  status: "success" | "failed" | "running"
  latencyMs?: number
}

export type Trace = {
  id: string
  query: string
  rewrittenQuery: string
  chunks: TraceChunk[]
  toolCalls?: ToolCallTrace[]
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
  toolCalls?: ToolCallTrace[]
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
  /** The document id once it exists on the server; a temporary id while the upload is in flight. */
  id: string
  name: string
  sizeBytes: number
  status: IngestionStatus
  progress: number
  error?: string
  driveUrl: string | null
  /** False for an upload that has not reached the server yet. */
  saved: boolean
  tags: string[]
  collections: { id: string; name: string }[]
  /** Legacy single-collection projection; new UI must use `collections`. */
  collection: string | null
  collectionId: string | null
  sharing: Sharing
  /** ISO timestamp of the last change to the document in Amber. */
  updatedAt: string
  /** Chunks stored in the vector store. */
  chunkCount: number
  /** The Amber user who added the file. */
  owner: { name: string | null; email: string | null }
  /** The Amber user who first initiated indexing; informational only. */
  importedBy: { name: string | null; email: string | null }
  /** False for files shared with the user by someone else. */
  isOwner: boolean
}

/** A folder of documents, owned by the signed-in user. */
export type Collection = {
  id: string
  name: string
  owner?: { name: string | null; email: string | null }
  isOwner?: boolean
  role?: string
  members?: { type: "user" | "domain"; value: string; role: "reader" | "writer" }[]
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
  drive: {
    connected: boolean
    can_share: boolean
    scopes: string[]
    permission_sync?: { active: boolean; expires_at: string | null; warning: string | null }
  }
}
