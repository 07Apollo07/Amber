"use client"

import { useMemo, useState } from "react"
import { ChevronRight, Folder, FolderOpen, FolderPlus, Inbox, MoreHorizontal, Pencil, Search, Share2, Trash2, X } from "lucide-react"
import { toast } from "sonner"

import { EmptyState } from "@/components/app/empty-state"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiPut } from "@/lib/api"
import type { Collection, UploadRow } from "@/lib/types"
import { cn } from "@/lib/utils"

import { CollectionDeleteDialog, CollectionNameDialog, CollectionShareDialog } from "./collection-dialogs"
import { FileRow } from "./file-row"

type Dialog =
  | { kind: "create" }
  | { kind: "rename" | "share" | "delete"; collection: Collection }

export function ManageFiles({
  pending,
  saved,
  collections,
  domain,
  onManage,
  onRemovePending,
  onChanged,
}: {
  pending: UploadRow[]
  saved: UploadRow[]
  collections: Collection[]
  domain: string | null
  onManage: (row: UploadRow) => void
  onRemovePending: (id: string) => void
  onChanged: () => void
}) {
  const [query, setQuery] = useState("")
  const [collectionFilter, setCollectionFilter] = useState("all")
  const [tagFilter, setTagFilter] = useState<string[]>([])
  const [closed, setClosed] = useState<Set<string>>(new Set())
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const allTags = useMemo(() => [...new Set(saved.flatMap((row) => row.tags))].sort(), [saved])
  const search = query.trim().toLowerCase()
  const matches = (row: UploadRow) =>
    row.name.toLowerCase().includes(search) &&
    tagFilter.every((tag) => row.tags.includes(tag)) &&
    (collectionFilter === "all" ||
      (collectionFilter === "none"
        ? row.collections.length === 0
        : row.collections.some((collection) => collection.id === collectionFilter)))
  const filtered = saved.filter(matches)
  const mine = filtered.filter((row) => row.isOwner)
  const shared = filtered.filter((row) => !row.isOwner)
  const empty = pending.length === 0 && saved.length === 0 && collections.length === 0

  function toggleTag(tag: string) {
    setTagFilter((current) => (current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]))
  }

  function toggleFolder(id: string, open: boolean) {
    setClosed((current) => {
      const next = new Set(current)
      if (open) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function toggleCollection(row: UploadRow, collectionId: string, included: boolean) {
    try {
      const response = await apiPut(`/api/collections/${collectionId}/documents/${row.id}`, { included })
      const result = (await response.json()) as { success: boolean; failed?: { member: string; error: string }[] }
      if (!result.success) {
        toast.error("Couldn't update collection membership", {
          description: result.failed?.map((item) => `${item.member}: ${item.error}`).join("\n"),
        })
        return
      }
      toast.success(included ? "Added to collection" : "Removed from collection")
      onChanged()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Couldn't update collection membership")
    }
  }

  const renderFileRow = (row: UploadRow) => (
    <FileRow
      key={row.id}
      row={row}
      collections={collections}
      onRemove={onRemovePending}
      onManage={onManage}
      onToggleCollection={(file, collectionId, included) => void toggleCollection(file, collectionId, included)}
      onChanged={onChanged}
    />
  )

  return (
    <div className="space-y-4">
      {empty ? (
        <EmptyState
          icon={Inbox}
          title="No files yet"
          description="Files you add from your computer or Google Drive will show up here."
          action={
            <Button variant="outline" onClick={() => setDialog({ kind: "create" })}>
              <FolderPlus /> New collection
            </Button>
          }
          className="rounded-2xl border border-dashed"
        />
      ) : (
        <Tabs defaultValue="files">
          <TabsList>
            <TabsTrigger value="files">File management</TabsTrigger>
            <TabsTrigger value="collections">Collections</TabsTrigger>
          </TabsList>

          <TabsContent value="files" className="space-y-4">
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
                  {collections.map((collection) => (
                    <SelectItem key={collection.id} value={collection.id}>{collection.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {allTags.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by tag">
                <span className="mr-1 text-xs text-muted-foreground">Tags</span>
                {allTags.map((tag) => {
                  const active = tagFilter.includes(tag)
                  return (
                    <button
                      key={tag}
                      type="button"
                      aria-pressed={active}
                      onClick={() => toggleTag(tag)}
                      className={cn(
                        "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                        active ? "border-primary/50 bg-primary/15 text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      )}
                    >
                      #{tag}
                    </button>
                  )
                })}
                {(search || collectionFilter !== "all" || tagFilter.length > 0) && (
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
                  {pending.map(renderFileRow)}
                </ul>
              </section>
            )}

            <Tabs defaultValue="my-files">
              <TabsList>
                <TabsTrigger value="my-files">My files ({mine.length})</TabsTrigger>
                <TabsTrigger value="shared-with-me">Shared with me ({shared.length})</TabsTrigger>
              </TabsList>
              <TabsContent value="my-files">
                {mine.length ? (
                  <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border bg-card/40">{mine.map(renderFileRow)}</ul>
                ) : <p className="py-6 text-center text-sm text-muted-foreground">No files owned by you match these filters.</p>}
              </TabsContent>
              <TabsContent value="shared-with-me">
                {shared.length ? (
                  <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border bg-card/40">{shared.map(renderFileRow)}</ul>
                ) : <p className="py-6 text-center text-sm text-muted-foreground">No files shared with you match these filters.</p>}
              </TabsContent>
            </Tabs>
          </TabsContent>

          <TabsContent value="collections" className="space-y-4">
            <div className="flex justify-end">
              <Button variant="outline" onClick={() => setDialog({ kind: "create" })}>
                <FolderPlus /> New collection
              </Button>
            </div>
            {collections.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No collections yet. Create one to organize files and share them with collaborators.
              </p>
            ) : (
              <div className="space-y-3">
                {collections.map((collection) => {
                  const rows = saved.filter((row) => row.collections.some((item) => item.id === collection.id))
                  return (
                    <FolderGroup
                      key={collection.id}
                      id={collection.id}
                      title={collection.name}
                      rows={rows}
                      collections={collections}
                      open={!closed.has(collection.id)}
                      onOpenChange={(open) => toggleFolder(collection.id, open)}
                      onManage={onManage}
                      onRemove={onRemovePending}
                      onToggleCollection={toggleCollection}
                      onChanged={onChanged}
                      menu={collection.isOwner ? (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-sm" aria-label={`${collection.name} options`}>
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onSelect={() => setDialog({ kind: "share", collection })}>
                              <Share2 /> Share collection
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
                      ) : null}
                    />
                  )
                })}
              </div>
            )}
          </TabsContent>
        </Tabs>
      )}

      {dialog?.kind === "create" && <CollectionNameDialog onClose={() => setDialog(null)} onDone={onChanged} />}
      {dialog?.kind === "rename" && (
        <CollectionNameDialog collection={dialog.collection} onClose={() => setDialog(null)} onDone={onChanged} />
      )}
      {dialog?.kind === "share" && (
        <CollectionShareDialog
          collection={dialog.collection}
          domain={domain}
          onClose={() => setDialog(null)}
          onDone={onChanged}
        />
      )}
      {dialog?.kind === "delete" && (
        <CollectionDeleteDialog
          collection={dialog.collection}
          count={saved.filter((row) => row.collections.some((item) => item.id === dialog.collection.id)).length}
          onClose={() => setDialog(null)}
          onDone={onChanged}
        />
      )}
    </div>
  )
}

function FolderGroup({
  title,
  rows,
  collections,
  open,
  onOpenChange,
  onManage,
  onRemove,
  onToggleCollection,
  onChanged,
  menu,
}: {
  id: string
  title: string
  rows: UploadRow[]
  collections: Collection[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onManage: (row: UploadRow) => void
  onRemove: (id: string) => void
  onToggleCollection: (row: UploadRow, collectionId: string, included: boolean) => Promise<void>
  onChanged: () => void
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
            This collection is empty. Use a file&apos;s Collections menu to add documents.
          </p>
        ) : (
          <ul className="divide-y divide-border/60 border-t">
            {rows.map((row) => (
              <FileRow
                key={row.id}
                row={row}
                collections={collections}
                onRemove={onRemove}
                onManage={onManage}
                onToggleCollection={(file, collectionId, included) =>
                  void onToggleCollection(file, collectionId, included)
                }
                onChanged={onChanged}
              />
            ))}
          </ul>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
