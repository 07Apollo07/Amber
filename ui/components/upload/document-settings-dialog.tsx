"use client"

import { useState } from "react"
import { Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { apiDelete, apiPut } from "@/lib/api"
import type { Sharing, UploadRow } from "@/lib/types"

import { OrganizeFields } from "./organize-fields"
import { SharingSelector } from "./sharing-selector"

/** Edit one document's collection, tags and who can access it. Mounted only while open, so it starts from the row's current values. */
export function DocumentSettingsDialog({
  row,
  domain,
  knownTags,
  onClose,
  onSaved,
}: {
  row: UploadRow
  domain: string | null
  knownTags: string[]
  onClose: () => void
  onSaved: () => void
}) {
  const [tags, setTags] = useState(row.tags)
  const [sharing, setSharing] = useState<Sharing>(row.sharing)
  const [saving, setSaving] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const busy = saving || deleting

  async function remove() {
    setDeleting(true)
    try {
      await apiDelete(`/api/documents/${row.id}`)
      toast.success("Document and its chunks deleted")
      onSaved()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't delete the document")
    } finally {
      setDeleting(false)
    }
  }

  async function save() {
    setSaving(true)
    try {
      await apiPut(`/api/documents/${row.id}/organize`, {
        collection: null,
        tags,
      })
      await apiPut(`/api/documents/${row.id}/access`, {
        kind: sharing.kind,
        emails: sharing.kind === "people" ? sharing.emails : [],
      })
      toast.success("Document updated")
      onSaved()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save changes")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="truncate">{row.name}</DialogTitle>
          <DialogDescription>Choose how this document is organized and who can find it in Amber.</DialogDescription>
        </DialogHeader>
        <div className="space-y-6">
          <section>
            <h3 className="mb-3 text-sm font-medium">Organize</h3>
            <OrganizeFields
              idPrefix="doc-"
              collection="none"
              onCollectionChange={() => undefined}
              tags={tags}
              onTagsChange={setTags}
              knownTags={knownTags}
              showCollection={false}
            />
          </section>
          <section>
            <h3 className="mb-3 text-sm font-medium">Who can access</h3>
            <SharingSelector value={sharing} onChange={setSharing} domain={domain} />
          </section>
          <section className="rounded-lg border border-destructive/30 p-3">
            <h3 className="text-sm font-medium text-destructive">Delete document</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Removes this file and all its indexed chunks from Amber. The original stays in Google Drive.
            </p>
            {confirmingDelete ? (
              <div className="mt-3 flex gap-2">
                <Button variant="destructive" size="sm" onClick={remove} disabled={busy}>
                  {deleting && <Loader2 className="animate-spin" />} Yes, delete
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmingDelete(false)} disabled={busy}>
                  Keep it
                </Button>
              </div>
            ) : (
              <Button variant="outline" size="sm" className="mt-3" onClick={() => setConfirmingDelete(true)} disabled={busy}>
                <Trash2 /> Delete…
              </Button>
            )}
          </section>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={save} disabled={busy}>
            {saving && <Loader2 className="animate-spin" />} Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
