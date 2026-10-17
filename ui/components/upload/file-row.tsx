"use client"

import { useState } from "react"
import { Building2, ChevronRight, ExternalLink, FolderPlus, Lock, Settings2, UsersRound, X } from "lucide-react"

import { StatusBadge } from "@/components/app/status-badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Progress } from "@/components/ui/progress"
import { formatBytes } from "@/lib/format"
import type { Collection, Sharing, UploadRow } from "@/lib/types"
import { cn } from "@/lib/utils"

import { CollectionNameDialog } from "./collection-dialogs"

export function sharingLabel(sharing: Sharing) {
  if (sharing.kind === "domain") return { icon: Building2, text: `Everyone at @${sharing.domain}` }
  if (sharing.kind === "people") {
    const n = sharing.emails.length
    return { icon: UsersRound, text: `${n} ${n === 1 ? "person" : "people"}` }
  }
  return { icon: Lock, text: "Only you" }
}

type Person = { name: string | null; email: string | null }

function personLabel(p: Person) {
  if (p.name && p.email) return `${p.name} (${p.email})`
  return p.name ?? p.email ?? "Unknown"
}

/** One document in Manage Files. Saved documents expand to show owner, sharing, last update and indexing details. */
export function FileRow({
  row,
  collections,
  onRemove,
  onManage,
  onToggleCollection,
  onChanged,
}: {
  row: UploadRow
  collections: Collection[]
  onRemove: (id: string) => void
  onManage: (row: UploadRow) => void
  onToggleCollection: (row: UploadRow, collectionId: string, included: boolean) => void
  onChanged?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const inProgress = row.status !== "ready" && row.status !== "failed"
  const { icon: ShareIcon, text } = sharingLabel(row.sharing)

  function toggle(next: boolean) {
    setOpen(next)
  }

  const header = (
    <div className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {row.saved && (
            <CollapsibleTrigger
              className="-ml-1 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label={open ? `Hide details for ${row.name}` : `Show details for ${row.name}`}
            >
              <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} />
            </CollapsibleTrigger>
          )}
          <span className="truncate text-sm font-medium">{row.name}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(row.sizeBytes)}</span>
        </div>
        {row.error && !row.saved ? (
          <p className="mt-1 text-xs break-words text-destructive">{row.error}</p>
        ) : row.error ? (
          <p className="mt-1 line-clamp-1 text-xs text-destructive">{row.error}</p>
        ) : inProgress ? (
          <Progress value={row.progress} className="mt-2 h-1.5" aria-label={`${row.name} progress`} />
        ) : null}
        {row.saved && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <ShareIcon className="size-3.5" /> {text}
            </span>
            {row.tags.map((tag) => (
              <span key={tag} className="rounded-full border px-2 py-0.5">
                #{tag}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 sm:justify-end">
        <StatusBadge status={row.status} />
        {row.driveUrl && (
          <Button variant="ghost" size="icon-sm" asChild>
            <a href={row.driveUrl} target="_blank" rel="noopener noreferrer" aria-label={`Open ${row.name} in Drive`}>
              <ExternalLink />
            </a>
          </Button>
        )}
        {row.saved && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" aria-label={`Choose collections for ${row.name}`}>
                Collections · {row.collections.length}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              {collections.map((collection) => (
                <DropdownMenuCheckboxItem
                  key={collection.id}
                  checked={row.collections.some((item) => item.id === collection.id)}
                  onCheckedChange={(included) => onToggleCollection(row, collection.id, included)}
                >
                  {collection.name}
                </DropdownMenuCheckboxItem>
              ))}
              {collections.length > 0 && <DropdownMenuSeparator />}
              <DropdownMenuItem
                onSelect={(event) => {
                  event.preventDefault()
                  setCreating(true)
                }}
              >
                <FolderPlus className="size-4" /> New collection
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        {creating && (
          <CollectionNameDialog
            onClose={() => setCreating(false)}
            onDone={onChanged ?? (() => {})}
            onCreated={(created) => {
              void onToggleCollection(row, created.id, true)
            }}
          />
        )}
        {row.saved && row.isOwner && (
          <Button variant="outline" size="sm" onClick={() => onManage(row)}>
            <Settings2 /> Manage
          </Button>
        )}
        {!row.saved && !inProgress && (
          <Button variant="ghost" size="icon-sm" aria-label={`Dismiss ${row.name}`} onClick={() => onRemove(row.id)}>
            <X />
          </Button>
        )}
      </div>
    </div>
  )

  if (!row.saved) return <li>{header}</li>

  const people = row.sharing.kind === "people" ? row.sharing.emails : []
  const updated = new Date(row.updatedAt)

  return (
    <li>
      <Collapsible open={open} onOpenChange={toggle}>
        {header}
        <CollapsibleContent>
          <dl className="grid gap-x-6 gap-y-3 border-t bg-muted/20 px-4 py-3 text-sm sm:grid-cols-2">
            <Detail label="Shared with">
              {row.sharing.kind === "domain" ? (
                `Everyone at @${row.sharing.domain}`
              ) : people.length > 0 ? (
                <>
                  {people.length} {people.length === 1 ? "person" : "people"}
                  <span className="mt-0.5 block text-xs break-all text-muted-foreground">{people.join(", ")}</span>
                </>
              ) : (
                "Only the owner (0 people)"
              )}
            </Detail>
            <Detail label="Owner in Google Drive">{personLabel(row.owner)}</Detail>
            <Detail label="Added to Amber by">{personLabel(row.importedBy)}</Detail>
            <Detail label="Last updated">
              {Number.isNaN(updated.getTime())
                ? "Unknown"
                : updated.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
            </Detail>
            <Detail label="Vector store">
              {row.status === "failed" ? (
                <span className="text-destructive">Not added</span>
              ) : inProgress ? (
                "Being added…"
              ) : (
                `${row.chunkCount} ${row.chunkCount === 1 ? "chunk" : "chunks"} added`
              )}
            </Detail>
          </dl>
          {row.status === "failed" && (
            <div className="border-t border-destructive/25 bg-destructive/5 px-4 py-3" role="alert">
              <p className="text-xs font-medium text-destructive">Why it failed</p>
              <p className="mt-1 text-sm break-words whitespace-pre-wrap">{row.error ?? "No error details were recorded."}</p>
            </div>
          )}
        </CollapsibleContent>
      </Collapsible>
    </li>
  )
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  )
}
