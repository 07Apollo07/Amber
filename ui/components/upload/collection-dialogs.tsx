"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { apiDelete, apiPost, apiPut } from "@/lib/api"
import type { Collection, Sharing } from "@/lib/types"

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
  onCreated,
}: {
  collection?: Collection
  onClose: () => void
  onDone: () => void
  onCreated?: (created: { id: string; name: string }) => void
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
      const res = await apiPost("/api/collections", { name: trimmed })
      const created = (await res.json()) as { id: string; name: string }
      if (onCreated) onCreated(created)
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

/** Adds/removes collection collaborators and propagates their access to the collection's Drive files. */
export function CollectionShareDialog({
  collection,
  domain,
  onClose,
  onDone,
}: {
  collection: Collection
  domain: string | null
  onClose: () => void
  onDone: () => void
}) {
  const [sharing, setSharing] = useState<Sharing>(() => {
    const members = collection.members ?? []
    const domainMember = members.find((member) => member.type === "domain")
    if (domainMember) return { kind: "domain", domain: domainMember.value }
    const emails = members.filter((member) => member.type === "user").map((member) => member.value)
    return emails.length ? { kind: "people", emails } : { kind: "private" }
  })
  const { busy, run } = useAction(() => {
    onDone()
    onClose()
  })

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="truncate">Share “{collection.name}”</DialogTitle>
          <DialogDescription>
            People you add get view access to every current file and to files added later. Amber changes only the
            collection&apos;s Drive grants; direct permissions managed elsewhere are left alone.
          </DialogDescription>
        </DialogHeader>
        <SharingSelector value={sharing} onChange={setSharing} domain={domain} />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              run(async () => {
                const res = await apiPut(`/api/collections/${collection.id}/access`, {
                  kind: sharing.kind,
                  emails: sharing.kind === "people" ? sharing.emails : [],
                  domain: sharing.kind === "domain" ? sharing.domain : null,
                })
                const { added, removed, failed } = (await res.json()) as {
                  added: number
                  removed: number
                  failed: { title: string; error: string }[]
                }
                if (failed.length > 0) {
                  toast.error(`${failed.length} ${failed.length === 1 ? "file" : "files"} couldn't be shared`, {
                    description: failed.map((f) => `${f.title}: ${f.error}`).join("\n"),
                    duration: 12000,
                  })
                }
                if (failed.length === 0) return "Collection access updated"
                if (added + removed > 0) return undefined
              })
            }
          >
            {busy && <Loader2 className="animate-spin" />} Update access
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
                const response = await apiDelete(`/api/collections/${collection.id}`)
                const result = (await response.json()) as {
                  failed: { title: string; member: string; error: string }[]
                }
                if (result.failed.length > 0) {
                  toast.error("Collection deleted, but some Drive access couldn't be removed", {
                    description: result.failed
                      .map((item) => `${item.title} (${item.member}): ${item.error}`)
                      .join("\n"),
                    duration: 12000,
                  })
                  return undefined
                }
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
