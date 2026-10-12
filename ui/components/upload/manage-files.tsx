"use client"

import { useMemo, useState } from "react"
import { ChevronRight, Folder, FolderOpen, FolderPlus, Inbox, MoreHorizontal, Pencil, Search, Share2, Trash2, X } from "lucide-react"

import { EmptyState } from "@/components/app/empty-state"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { Collection, UploadRow } from "@/lib/types"
import { cn } from "@/lib/utils"

import { CollectionDeleteDialog, CollectionNameDialog, CollectionShareDialog } from "./collection-dialogs"
import { FileRow } from "./file-row"

type Dialog =
  | { kind: "create" }
  | { kind: "rename" | "share" | "delete"; collection: Collection }

/** All of the user's documents, grouped into collection folders, with search and collection/tag filters. */
export function ManageFiles({
  pending,
  saved,
  collections,
  domain,
  onManage,
  onRemovePending,
  onChanged,
}: {
  /** Uploads still in flight or failed. */
  pending: UploadRow[]
  saved: UploadRow[]
  collections: Collection[]
  domain: string | null
  onManage: (row: UploadRow) => void
  onRemovePending: (id: string) => void
  /** Called after any change made here so the page can reload. */
  onChanged: () => void
}) {
  const [query, setQuery] = useState("")
  const [collectionFilter, setCollectionFilter] = useState("all") // "all" | "none" | collection id
  const [tagFilter, setTagFilter] = useState<string[]>([])
  const [closed, setClosed] = useState<Set<string>>(new Set())
  const [dialog, setDialog] = useState<Dialog | null>(null)

  const allTags = useMemo(() => [...new Set(saved.flatMap((r) => r.tags))].sort(), [saved])
  const filtering = query.trim() !== "" || collectionFilter !== "all" || tagFilter.length > 0

  const matches = (row: UploadRow) =>
    row.name.toLowerCase().includes(query.trim().toLowerCase()) &&
    tagFilter.every((t) => row.tags.includes(t)) &&
    (collectionFilter === "all" || (collectionFilter === "none" ? !row.collectionId : row.collectionId === collectionFilter))

  const visible = saved.filter(matches)
  const folders = collections
    .filter((c) => collectionFilter === "all" || collectionFilter === c.id)
    .map((c) => ({ collection: c, rows: visible.filter((r) => r.collectionId === c.id) }))
    .filter((f) => !filtering || f.rows.length > 0)
  const ungrouped = visible.filter((r) => !r.collectionId)

  function toggleTag(tag: string) {
    setTagFilter((t) => (t.includes(tag) ? t.filter((x) => x !== tag) : [...t, tag]))
  }

  function toggleFolder(id: string, open: boolean) {
    setClosed((prev) => {
      const next = new Set(prev)
      if (open) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const nothing = pending.length === 0 && saved.length === 0 && collections.length === 0

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search files"
            aria-label="Search files"
            className="pl-9"
          />
        </div>
        <Select value={collectionFilter} onValueChange={setCollectionFilter}>
          <SelectTrigger className="sm:w-48" aria-label="Filter by collection">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All collections</SelectItem>
            <SelectItem value="none">No collection</SelectItem>
            {collections.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" onClick={() => setDialog({ kind: "create" })}>
          <FolderPlus /> New collection
        </Button>
      </div>

      {allTags.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by tag">
          <span className="mr-1 text-xs text-muted-foreground">Tags</span>
          {allTags.map((tag) => {
            const on = tagFilter.includes(tag)
            return (
              <button
                key={tag}
                type="button"
                aria-pressed={on}
                onClick={() => toggleTag(tag)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                  on ? "border-primary/50 bg-primary/15 text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                #{tag}
              </button>
            )
          })}
          {filtering && (
            <Button
              variant="ghost"
              size="xs"
              className="text-muted-foreground"
              onClick={() => {
                setQuery("")
                setCollectionFilter("all")
                setTagFilter([])
              }}
            >
              <X /> Clear filters
            </Button>
          )}
        </div>
      )}

      {pending.length > 0 && (
        <section aria-label="Uploading">
          <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">Uploading</h3>
          <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border bg-card/40">
            {pending.map((row) => (
              <FileRow key={row.id} row={row} onRemove={onRemovePending} onManage={onManage} />
            ))}
          </ul>
        </section>
      )}

      {nothing ? (
        <EmptyState
          icon={Inbox}
          title="No files yet"
          description="Files you add from your computer or Google Drive will show up here."
          className="rounded-2xl border border-dashed"
        />
      ) : (
        <div className="space-y-3">
          {folders.map(({ collection, rows }) => (
            <FolderGroup
              key={collection.id}
              id={collection.id}
              title={collection.name}
              rows={rows}
              open={!closed.has(collection.id)}
              onOpenChange={(open) => toggleFolder(collection.id, open)}
              onManage={onManage}
              onRemove={onRemovePending}
              menu={
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon-sm" aria-label={`${collection.name} options`}>
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setDialog({ kind: "share", collection })} disabled={rows.length === 0}>
                      <Share2 /> Share all files
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => setDialog({ kind: "rename", collection })}>
                      <Pencil /> Rename
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="destructive" onSelect={() => setDialog({ kind: "delete", collection })}>
                      <Trash2 /> Delete collection
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              }
            />
          ))}
          {ungrouped.length > 0 && (
            <FolderGroup
              id="none"
              title="No collection"
              rows={ungrouped}
              open={!closed.has("none")}
              onOpenChange={(open) => toggleFolder("none", open)}
              onManage={onManage}
              onRemove={onRemovePending}
            />
          )}
          {filtering && visible.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">No files match these filters.</p>
          )}
        </div>
      )}

      {dialog?.kind === "create" && <CollectionNameDialog onClose={() => setDialog(null)} onDone={onChanged} />}
      {dialog?.kind === "rename" && (
        <CollectionNameDialog collection={dialog.collection} onClose={() => setDialog(null)} onDone={onChanged} />
      )}
      {dialog?.kind === "share" && (
        <CollectionShareDialog
          collection={dialog.collection}
          rows={saved.filter((r) => r.collectionId === dialog.collection.id)}
          domain={domain}
          onClose={() => setDialog(null)}
          onDone={onChanged}
        />
      )}
      {dialog?.kind === "delete" && (
        <CollectionDeleteDialog
          collection={dialog.collection}
          count={saved.filter((r) => r.collectionId === dialog.collection.id).length}
          onClose={() => setDialog(null)}
          onDone={onChanged}
        />
      )}
    </div>
  )
}

/** A collapsible folder: a header with the name and file count, and its files underneath. */
function FolderGroup({
  title,
  rows,
  open,
  onOpenChange,
  onManage,
  onRemove,
  menu,
}: {
  id: string
  title: string
  rows: UploadRow[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onManage: (row: UploadRow) => void
  onRemove: (id: string) => void
  menu?: React.ReactNode
}) {
  const Icon = open ? FolderOpen : Folder
  return (
    <Collapsible open={open} onOpenChange={onOpenChange} className="overflow-hidden rounded-2xl border bg-card/40">
      <div className="flex items-center gap-1 pr-2">
        <CollapsibleTrigger className="flex min-w-0 flex-1 items-center gap-2 p-3 text-left hover:bg-muted/40">
          <ChevronRight className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
          <Icon className="size-5 shrink-0 fill-amber-500/20 text-amber-500" />
          <span className="truncate text-sm font-medium">{title}</span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {rows.length} {rows.length === 1 ? "file" : "files"}
          </span>
        </CollapsibleTrigger>
        {menu}
      </div>
      <CollapsibleContent>
        {rows.length === 0 ? (
          <p className="border-t px-4 py-4 text-sm text-muted-foreground">
            Empty. Pick this collection in Organize before adding files, or use Manage on a file to move it here.
          </p>
        ) : (
          <ul className="divide-y divide-border/60 border-t">
            {rows.map((row) => (
              <FileRow key={row.id} row={row} onRemove={onRemove} onManage={onManage} />
            ))}
          </ul>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
