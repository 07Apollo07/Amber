"use client"

import { useState } from "react"
import { AlertTriangle, Building2, ExternalLink, FileText, MessageSquareText, Search, Tag, User } from "lucide-react"

import { StatusBadge } from "@/components/app/status-badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { exactTime, timeAgo } from "@/lib/admin-activity"
import { formatBytes, ingestionStatusFromApi } from "@/lib/format"
import { cn } from "@/lib/utils"

import { useAdminData } from "./use-admin-data"
import { useDebounced, usePagedAdmin } from "./use-paged-admin"

type Grant = { type: "user" | "domain"; value: string; origin: string }
type Person = { name: string | null; email: string | null }
type AdminDocument = {
  id: string
  title: string
  file_type: string
  origin: "desktop_upload" | "drive_sync"
  status: string
  status_message: string | null
  sharing_option: "private" | "specific_people" | "domain"
  file_size_bytes: number
  chunk_count: number
  owner: Person
  imported_by: Person
  drive_url: string | null
  tags: string[]
  access: Grant[]
  created_at: string
  updated_at: string
}
type DocumentDetail = AdminDocument & { usage: { answers: number; people: number; last_used: string | null } }
type Counts = { total: number; ready: number; processing: number; failed: number; from_drive: number; uploaded: number; total_bytes: number }
type StatusGroup = "all" | "ready" | "processing" | "failed"

const SHARING: Record<AdminDocument["sharing_option"], string> = {
  private: "Private",
  specific_people: "Specific people",
  domain: "Whole domain",
}

const SOURCE: Record<AdminDocument["origin"], string> = { drive_sync: "Google Drive", desktop_upload: "Upload" }

function accessSummary(doc: AdminDocument) {
  const domain = doc.access.find((g) => g.type === "domain")
  if (domain) return `Everyone at @${domain.value}`
  const ownerEmail = doc.owner.email?.toLowerCase()
  const others = doc.access.filter((g) => g.type === "user" && g.value !== ownerEmail).length
  return others === 0 ? "Only the owner" : `${others} ${others === 1 ? "person" : "people"}`
}

function who(person: Person, fallback: string) {
  return person.name ?? person.email ?? fallback
}

const chips: { value: StatusGroup; label: string; count: (c: Counts) => number; tone?: string }[] = [
  { value: "all", label: "All documents", count: (c) => c.total },
  { value: "ready", label: "Ready", count: (c) => c.ready, tone: "text-success" },
  { value: "processing", label: "Processing", count: (c) => c.processing, tone: "text-info" },
  { value: "failed", label: "Failed", count: (c) => c.failed, tone: "text-destructive" },
]

export function DocumentsTab() {
  const [status, setStatus] = useState<StatusGroup>("all")
  const [origin, setOrigin] = useState("all")
  const [sharing, setSharing] = useState("all")
  const [text, setText] = useState("")
  const [openId, setOpenId] = useState<string | null>(null)
  const q = useDebounced(text.trim())
  const { items, raw, hasMore, loading, error, loadMore } = usePagedAdmin<AdminDocument>("/api/admin/documents", "documents", {
    status: status === "all" ? undefined : status,
    origin: origin === "all" ? undefined : origin,
    sharing: sharing === "all" ? undefined : sharing,
    q: q || undefined,
  })
  const counts = raw?.counts as Counts | undefined
  const filtered = status !== "all" || origin !== "all" || sharing !== "all" || q !== ""

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by status">
        {chips.map((chip) => (
          <button
            key={chip.value}
            type="button"
            aria-pressed={status === chip.value}
            onClick={() => setStatus(chip.value)}
            className={cn(
              "flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors",
              status === chip.value ? "border-primary bg-primary/10" : "bg-card/40 hover:bg-muted/60",
            )}
          >
            <span>{chip.label}</span>
            <span className={cn("font-semibold tabular-nums", chip.tone)}>{counts ? chip.count(counts).toLocaleString() : "–"}</span>
          </button>
        ))}
        {counts && counts.total > 0 && (
          <span className="ml-auto text-xs text-muted-foreground">
            {counts.from_drive.toLocaleString()} from Drive · {counts.uploaded.toLocaleString()} uploaded ·{" "}
            {formatBytes(counts.total_bytes)} in total
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Search title, owner or tag"
            className="pl-8"
            aria-label="Search documents"
          />
        </div>
        <Select value={origin} onValueChange={setOrigin}>
          <SelectTrigger className="w-40" aria-label="Filter by source">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All sources</SelectItem>
            <SelectItem value="drive_sync">Google Drive</SelectItem>
            <SelectItem value="desktop_upload">Uploads</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sharing} onValueChange={setSharing}>
          <SelectTrigger className="w-44" aria-label="Filter by sharing">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any sharing</SelectItem>
            {(Object.keys(SHARING) as AdminDocument["sharing_option"][]).map((key) => (
              <SelectItem key={key} value={key}>
                {SHARING[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground sm:ml-auto">You can review who has access. Admins can&apos;t read document text.</p>
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          Couldn&apos;t load documents: {error}
        </p>
      )}

      <div className="overflow-hidden rounded-2xl border bg-card/40">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Document</TableHead>
              <TableHead>Owner / added by</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Who can open it</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="pr-4">Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((doc) => (
              <TableRow key={doc.id} className="cursor-pointer" onClick={() => setOpenId(doc.id)}>
                <TableCell className="pl-4">
                  <div className="flex items-center gap-2.5">
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <button
                        type="button"
                        className="block max-w-[280px] truncate text-left font-medium hover:text-primary"
                        onClick={(e) => {
                          e.stopPropagation()
                          setOpenId(doc.id)
                        }}
                      >
                        {doc.title}
                      </button>
                      <div className="text-xs text-muted-foreground">
                        {doc.file_type.toUpperCase()} · {formatBytes(doc.file_size_bytes)}
                        {doc.chunk_count > 0 && ` · ${doc.chunk_count} passages`}
                      </div>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="text-sm">{who(doc.owner, "Unknown owner")}</div>
                  {doc.imported_by.email !== doc.owner.email && (
                    <div className="text-xs text-muted-foreground">Added by {who(doc.imported_by, "unknown")}</div>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">{SOURCE[doc.origin] ?? doc.origin}</TableCell>
                <TableCell>
                  <div className="text-sm">{SHARING[doc.sharing_option]}</div>
                  <div className="text-xs text-muted-foreground">{accessSummary(doc)}</div>
                </TableCell>
                <TableCell className="max-w-[220px]">
                  <StatusBadge status={ingestionStatusFromApi(doc.status)} />
                  {doc.status === "failed" && doc.status_message && (
                    <div className="mt-1 truncate text-xs text-destructive" title={doc.status_message}>
                      {doc.status_message}
                    </div>
                  )}
                </TableCell>
                <TableCell className="pr-4 whitespace-nowrap text-muted-foreground">
                  <time dateTime={doc.updated_at} title={exactTime(doc.updated_at)}>
                    {timeAgo(doc.updated_at)}
                  </time>
                </TableCell>
              </TableRow>
            ))}
            {!loading && items.length === 0 && !error && (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                  {filtered ? "No documents match these filters." : "No documents have been added yet."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      {loading && (
        <p role="status" className="flex items-center justify-center gap-2 py-2 text-sm text-muted-foreground">
          <Spinner /> Loading documents…
        </p>
      )}
      {hasMore && !loading && (
        <div className="flex justify-center">
          <Button variant="outline" onClick={() => void loadMore()}>
            Show more documents
          </Button>
        </div>
      )}

      <Sheet open={openId !== null} onOpenChange={(open) => !open && setOpenId(null)}>
        <SheetContent className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-none data-[side=right]:lg:w-[40vw]">
          {openId && <DocumentDetailView key={openId} documentId={openId} />}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

function DocumentDetailView({ documentId }: { documentId: string }) {
  const { data: doc, error } = useAdminData<DocumentDetail>(`/api/admin/documents/${documentId}`)

  if (error || !doc) {
    return (
      <SheetHeader>
        <SheetTitle className="flex items-center gap-2">{error ? "Document unavailable" : <><Spinner /> Loading document…</>}</SheetTitle>
        <SheetDescription role={error ? "alert" : undefined}>{error ?? "Loading"}</SheetDescription>
      </SheetHeader>
    )
  }

  const ownerEmail = doc.owner.email?.toLowerCase()
  return (
    <>
      <SheetHeader>
        <div className="mb-1">
          <StatusBadge status={ingestionStatusFromApi(doc.status)} />
        </div>
        <SheetTitle className="pr-6 text-base leading-snug break-words">{doc.title}</SheetTitle>
        <SheetDescription>
          {doc.file_type.toUpperCase()} · {formatBytes(doc.file_size_bytes)} · {SOURCE[doc.origin] ?? doc.origin}
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-6 px-4 pb-6">
        {doc.status === "failed" && (
          <div role="alert" className="flex gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
            <div className="min-w-0">
              <div className="font-medium">This document couldn&apos;t be indexed, so it won&apos;t appear in answers</div>
              {doc.status_message && (
                <div className="mt-1 break-words whitespace-pre-wrap text-muted-foreground">{doc.status_message}</div>
              )}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3 rounded-xl border bg-card/60 p-3">
          <MessageSquareText className="size-5 shrink-0 text-muted-foreground" />
          <div className="text-sm">
            {doc.usage.answers === 0 ? (
              "No chat answer has used this document yet."
            ) : (
              <>
                Found in <span className="font-semibold">{doc.usage.answers.toLocaleString()}</span>{" "}
                {doc.usage.answers === 1 ? "answer" : "answers"} for {doc.usage.people.toLocaleString()}{" "}
                {doc.usage.people === 1 ? "person" : "people"}
                {doc.usage.last_used && (
                  <span className="text-muted-foreground">
                    {" "}
                    · last <time title={exactTime(doc.usage.last_used)}>{timeAgo(doc.usage.last_used)}</time>
                  </span>
                )}
              </>
            )}
          </div>
        </div>

        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm">
          <Fact label="Owner">
            {who(doc.owner, "Unknown")}
            {doc.owner.name && doc.owner.email && <span className="text-muted-foreground"> · {doc.owner.email}</span>}
          </Fact>
          <Fact label="Added by">
            {who(doc.imported_by, "Unknown")}
            {doc.imported_by.name && doc.imported_by.email && (
              <span className="text-muted-foreground"> · {doc.imported_by.email}</span>
            )}
          </Fact>
          <Fact label="Added">{exactTime(doc.created_at)}</Fact>
          <Fact label="Last updated">{exactTime(doc.updated_at)}</Fact>
          <Fact label="Searchable passages">{doc.chunk_count.toLocaleString()}</Fact>
          <Fact label="Sharing">{SHARING[doc.sharing_option]}</Fact>
          {doc.tags.length > 0 && (
            <Fact label="Tags">
              <span className="flex flex-wrap gap-1">
                {doc.tags.map((tag) => (
                  <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs">
                    <Tag className="size-3" /> {tag}
                  </span>
                ))}
              </span>
            </Fact>
          )}
        </dl>

        {doc.drive_url && (
          <Button variant="outline" size="sm" asChild>
            <a href={doc.drive_url} target="_blank" rel="noopener noreferrer">
              <ExternalLink /> Open in Google Drive
            </a>
          </Button>
        )}

        <section>
          <h3 className="mb-1 text-sm font-semibold">Who can open it</h3>
          <p className="mb-2 text-xs text-muted-foreground">Amber only uses this document in answers for the people listed here.</p>
          <ul className="divide-y divide-border/60 rounded-xl border">
            {doc.access.map((g) => (
              <li key={`${g.type}:${g.value}`} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                {g.type === "domain" ? (
                  <Building2 className="size-4 shrink-0 text-muted-foreground" />
                ) : (
                  <User className="size-4 shrink-0 text-muted-foreground" />
                )}
                <span className="flex-1 break-all">{g.type === "domain" ? `Everyone at @${g.value}` : g.value}</span>
                <span className="text-xs whitespace-nowrap text-muted-foreground">
                  {g.type === "user" && g.value === ownerEmail
                    ? "Owner"
                    : g.origin === "drive_sync"
                      ? "From Google Drive"
                      : "Shared in Amber"}
                </span>
              </li>
            ))}
            {doc.access.length === 0 && <li className="px-3 py-2.5 text-sm text-muted-foreground">No one has access.</li>}
          </ul>
        </section>
      </div>
    </>
  )
}
