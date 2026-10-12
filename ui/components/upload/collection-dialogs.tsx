"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { apiDelete, apiPost, apiPut } from "@/lib/api"
import type { Collection, Sharing, UploadRow } from "@/lib/types"

import { SharingSelector } from "./sharing-selector"

/** Runs a save, reports failures as a toast, and closes on success. */
function useAction(onDone: () => void) {
  const [busy, setBusy] = useState(false)
  async function run(action: () => Promise<string | void>) {
    setBusy(true)
    try {
      const message = await action()
      if (message) toast.success(message)
      onDone()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Something went wrong")
    } finally {
      setBusy(false)
    }
  }
  return { busy, run }
}

/** Creates a collection, or renames it when `collection` is given. */
export function CollectionNameDialog({
  collection,
  onClose,
  onDone,
}: {
  collection?: Collection
  onClose: () => void
  onDone: () => void
}) {
  const [name, setName] = useState(collection?.name ?? "")
  const { busy, run } = useAction(() => {
    onDone()
    onClose()
  })

  function submit() {
    const trimmed = name.trim()
    if (!trimmed) return
    void run(async () => {
      if (collection) {
        await apiPut(`/api/collections/${collection.id}`, { name: trimmed })
        return "Collection renamed"
      }
      await apiPost("/api/collections", { name: trimmed })
      return "Collection created"
    })
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{collection ? "Rename collection" : "New collection"}</DialogTitle>
          <DialogDescription>
            {collection ? "Documents inside keep their place." : "A collection works like a folder for your documents."}
          </DialogDescription>
        </DialogHeader>
        <Input
          autoFocus
          value={name}
          maxLength={255}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && submit()}
          placeholder="Collection name"
          aria-label="Collection name"
        />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy || !name.trim()}>
            {busy && <Loader2 className="animate-spin" />} {collection ? "Rename" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Sets who can access every document in the collection at once. */
export function CollectionShareDialog({
  collection,
  rows,
  domain,
  onClose,
  onDone,
}: {
  collection: Collection
  rows: UploadRow[]
  domain: string | null
  onClose: () => void
  onDone: () => void
}) {
  // Start from the current sharing when every document agrees, otherwise from private.
  const [sharing, setSharing] = useState<Sharing>(() => {
    const first = rows[0]?.sharing
    return first && rows.every((r) => JSON.stringify(r.sharing) === JSON.stringify(first)) ? first : { kind: "private" }
  })
  const { busy, run } = useAction(() => {
    onDone()
    onClose()
  })
  const mixed = rows.length > 1 && new Set(rows.map((r) => JSON.stringify(r.sharing))).size > 1

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="truncate">Share “{collection.name}”</DialogTitle>
          <DialogDescription>
            This sets access for all {rows.length} {rows.length === 1 ? "document" : "documents"} in the collection
            {mixed ? ", replacing the different access they have now" : ""}. Files you add later aren&apos;t included.
          </DialogDescription>
        </DialogHeader>
        <SharingSelector value={sharing} onChange={setSharing} domain={domain} />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            disabled={busy || rows.length === 0}
            onClick={() =>
              run(async () => {
                const res = await apiPut(`/api/collections/${collection.id}/access`, {
                  kind: sharing.kind,
                  emails: sharing.kind === "people" ? sharing.emails : [],
                })
                const { updated, failed } = (await res.json()) as {
                  updated: number
                  failed: { title: string; error: string }[]
                }
                if (failed.length > 0) {
                  toast.error(`${failed.length} ${failed.length === 1 ? "file" : "files"} couldn't be shared`, {
                    description: failed.map((f) => `${f.title}: ${f.error}`).join("\n"),
                    duration: 12000,
                  })
                }
                if (updated > 0) return `Updated access for ${updated} ${updated === 1 ? "document" : "documents"}`
              })
            }
          >
            {busy && <Loader2 className="animate-spin" />} Apply to all
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function CollectionDeleteDialog({
  collection,
  count,
  onClose,
  onDone,
}: {
  collection: Collection
  count: number
  onClose: () => void
  onDone: () => void
}) {
  const { busy, run } = useAction(() => {
    onDone()
    onClose()
  })
  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Delete “{collection.name}”?</DialogTitle>
          <DialogDescription>
            {count === 0
              ? "The collection is empty."
              : `The ${count} ${count === 1 ? "document" : "documents"} inside won't be deleted. They move to No collection.`}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await apiDelete(`/api/collections/${collection.id}`)
                return "Collection deleted"
              })
            }
          >
            {busy && <Loader2 className="animate-spin" />} Delete collection
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
