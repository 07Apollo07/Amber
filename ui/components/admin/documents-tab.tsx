"use client"

import { useState } from "react"
import { Building2, Eye, FileText, Search, User } from "lucide-react"

import { StatusBadge } from "@/components/app/status-badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatBytes, ingestionStatusFromApi } from "@/lib/format"

import { useAdminData } from "./use-admin-data"

type Grant = { type: "user" | "domain"; value: string; origin: string }
type AdminDocument = {
  id: string
  title: string
  file_type: string
  origin: string
  status: string
  status_message: string | null
  sharing_option: "private" | "specific_people" | "domain"
  file_size_bytes: number
  chunk_count: number
  owner: { name: string | null; email: string | null }
  imported_by: { name: string | null; email: string | null }
  drive_url: string | null
  tags: string[]
  access: Grant[]
  created_at: string
  updated_at: string
}

const SHARING: Record<AdminDocument["sharing_option"], string> = {
  private: "Private",
  specific_people: "Specific people",
  domain: "Whole domain",
}

function accessSummary(doc: AdminDocument) {
  const domain = doc.access.find((g) => g.type === "domain")
  if (domain) return `Everyone at @${domain.value}`
  const ownerEmail = doc.owner.email?.toLowerCase()
  const others = doc.access.filter((g) => g.type === "user" && g.value !== ownerEmail).length
  return others === 0 ? "Only the owner" : `${others} ${others === 1 ? "person" : "people"}`
}

export function DocumentsTab() {
  const { data, error } = useAdminData<{ documents: AdminDocument[] }>("/api/admin/documents")
  const [query, setQuery] = useState("")
  const [aclDoc, setAclDoc] = useState<AdminDocument | null>(null)
  const needle = query.toLowerCase()
  const rows = (data?.documents ?? []).filter((d) =>
    `${d.title} ${d.owner.name ?? ""} ${d.owner.email ?? ""} ${d.imported_by.name ?? ""} ${d.imported_by.email ?? ""} ${d.tags.join(" ")}`.toLowerCase().includes(needle),
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by title, owner or tag"
            className="pl-8"
            aria-label="Filter documents"
          />
        </div>
        <p className="text-xs text-muted-foreground">You can review who has access. Admins can&apos;t read document text.</p>
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
              <TableHead>Drive owner / added by</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Access</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Chunks</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="pl-4">
                  <div className="flex items-center gap-2.5">
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="max-w-[260px] truncate font-medium">{doc.title}</div>
                      <div className="text-xs text-muted-foreground">
                        {doc.file_type.toUpperCase()} · {formatBytes(doc.file_size_bytes)}
                      </div>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="text-sm">{doc.owner.name ?? doc.owner.email ?? "Unknown Drive owner"}</div>
                  <div className="text-xs text-muted-foreground">Owner · {doc.owner.email ?? "Unknown"}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    Added by · {doc.imported_by.name ?? doc.imported_by.email ?? "Unknown"}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">{doc.origin === "drive_sync" ? "Drive" : "Upload"}</TableCell>
                <TableCell>
                  <div className="text-sm">{SHARING[doc.sharing_option]}</div>
                  <div className="text-xs text-muted-foreground">{accessSummary(doc)}</div>
                </TableCell>
                <TableCell>
                  <StatusBadge status={ingestionStatusFromApi(doc.status)} />
                </TableCell>
                <TableCell className="text-right tabular-nums">{doc.chunk_count}</TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(doc.updated_at).toLocaleDateString(undefined, { dateStyle: "medium" })}
                </TableCell>
                <TableCell>
                  <Button variant="ghost" size="icon-sm" aria-label={`View access for ${doc.title}`} onClick={() => setAclDoc(doc)}>
                    <Eye />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {data && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="py-10 text-center text-muted-foreground">
                  {query ? `No documents match “${query}”.` : "No documents have been added yet."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={aclDoc !== null} onOpenChange={(open) => !open && setAclDoc(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="pr-6">Who can access “{aclDoc?.title}”</DialogTitle>
            <DialogDescription>
              Owned by {aclDoc?.owner.email ?? "an unknown Drive owner"}. Search results are filtered by this list.
            </DialogDescription>
          </DialogHeader>
          <ul className="divide-y divide-border/60 rounded-xl border">
            {aclDoc?.access.map((g) => (
              <li key={`${g.type}:${g.value}`} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                {g.type === "domain" ? <Building2 className="size-4 text-muted-foreground" /> : <User className="size-4 text-muted-foreground" />}
                <span className="flex-1 break-all">{g.type === "domain" ? `Everyone at @${g.value}` : g.value}</span>
                <span className="text-xs text-muted-foreground">
                  {g.type === "user" && g.value === aclDoc.owner.email?.toLowerCase()
                    ? "Owner"
                    : g.origin === "drive_sync"
                      ? "From Google Drive"
                      : "Shared in Amber"}
                </span>
              </li>
            ))}
            {aclDoc?.access.length === 0 && <li className="px-3 py-2.5 text-sm text-muted-foreground">No access entries.</li>}
          </ul>
          {aclDoc?.status_message && aclDoc.status === "failed" && (
            <p role="alert" className="text-xs break-words whitespace-pre-wrap text-destructive">
              {aclDoc.status_message}
            </p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
