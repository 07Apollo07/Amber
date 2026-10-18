import type { FileType, IngestionStatus } from "./types"

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export const fileTypeLabel: Record<FileType, string> = {
  pdf: "PDF",
  docx: "Word",
  pptx: "PowerPoint",
  xlsx: "Excel",
  txt: "Text",
  md: "Markdown",
  gdoc: "Google Doc",
  gsheet: "Google Sheet",
  gslides: "Google Slides",
}

export const statusLabel: Record<IngestionStatus, string> = {
  queued: "Queued",
  saving_to_drive: "Saving to Drive",
  parsing: "Parsing",
  embedding: "Embedding",
  ready: "Ready",
  failed: "Failed",
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
}

/** Maps the API's document status to the UI's. */
export function ingestionStatusFromApi(status: string): IngestionStatus {
  const map: Record<string, IngestionStatus> = {
    queued: "queued",
    saving_to_drive: "saving_to_drive",
    parsing: "parsing",
    indexing: "embedding",
    indexed: "ready",
    failed: "failed",
  }
  return map[status] ?? "queued"
}
