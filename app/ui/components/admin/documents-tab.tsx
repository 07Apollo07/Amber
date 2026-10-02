"use client"

import { useState } from "react"
import { Building2, Eye, MoreHorizontal, RotateCw, Search, Trash2, User } from "lucide-react"

import { FileIcon } from "@/components/app/file-icon"
import { SharingSummary } from "@/components/app/sharing-summary"
import { StatusBadge } from "@/components/app/status-badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { demoAction } from "@/lib/demo"
import { documents } from "@/lib/mock-data"
import type { AmberDocument } from "@/lib/types"

function accessList(doc: AmberDocument) {
  const owner = { type: "user", value: doc.owner, note: "Owner" }
  if (doc.sharing.kind === "private") return [owner]
  if (doc.sharing.kind === "domain") return [owner, { type: "domain", value: doc.sharing.domain, note: "Drive: domain reader" }]
  return [owner, ...doc.sharing.emails.map((e) => ({ type: "user", value: e, note: "Drive: reader" }))]
}

export function DocumentsTab() {
  const [query, setQuery] = useState("")
  const [aclDoc, setAclDoc] = useState<AmberDocument | null>(null)
  const rows = documents.filter((d) => `${d.title} ${d.owner}`.toLowerCase().includes(query.toLowerCase()))

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by title or owner" className="pl-8" aria-label="Filter documents" />
      </div>
      <div className="overflow-hidden rounded-2xl border bg-card/40">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Document</TableHead>
              <TableHead>Owner</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Access</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="pl-4">
                  <div className="flex items-center gap-2.5">
                    <FileIcon type={doc.fileType} className="size-7" />
                    <span className="max-w-[260px] truncate font-medium">{doc.title}</span>
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">{doc.owner}</TableCell>
                <TableCell className="text-muted-foreground">{doc.origin === "drive_picker" ? "Drive" : "Upload"}</TableCell>
                <TableCell>
                  <SharingSummary sharing={doc.sharing} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={doc.status} />
                </TableCell>
                <TableCell className="text-muted-foreground">{doc.updatedAt}</TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${doc.title}`}>
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => setAclDoc(doc)}>
                        <Eye /> View access
                      </DropdownMenuItem>
                      <DropdownMenuItem onSelect={() => demoAction("Re-index queued")}>
                        <RotateCw /> Re-index
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem variant="destructive" onSelect={() => demoAction("Removed from index")}>
                        <Trash2 /> Remove from index
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                  No documents match “{query}”.
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
            <DialogDescription>Synced from Google Drive sharing. Search results are filtered by this list.</DialogDescription>
          </DialogHeader>
          <ul className="divide-y divide-border/60 rounded-xl border">
            {aclDoc &&
              accessList(aclDoc).map((p) => (
                <li key={p.value} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                  {p.type === "domain" ? <Building2 className="size-4 text-muted-foreground" /> : <User className="size-4 text-muted-foreground" />}
                  <span className="flex-1">{p.type === "domain" ? `Everyone at @${p.value}` : p.value}</span>
                  <span className="text-xs text-muted-foreground">{p.note}</span>
                </li>
              ))}
          </ul>
        </DialogContent>
      </Dialog>
    </div>
  )
}
