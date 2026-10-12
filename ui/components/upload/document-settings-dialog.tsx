"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { apiPut } from "@/lib/api"
import type { Collection, Sharing, UploadRow } from "@/lib/types"

import { OrganizeFields } from "./organize-fields"
import { SharingSelector } from "./sharing-selector"

/** Edit one document's collection, tags and who can access it. Mounted only while open, so it starts from the row's current values. */
export function DocumentSettingsDialog({
  row,
  domain,
  collections,
  knownTags,
  onClose,
  onSaved,
}: {
  row: UploadRow
  domain: string | null
  collections: Collection[]
  knownTags: string[]
  onClose: () => void
  onSaved: () => void
}) {
  const [collection, setCollection] = useState(row.collection ?? "none")
  const [tags, setTags] = useState(row.tags)
  const [sharing, setSharing] = useState<Sharing>(row.sharing)
  const [saving, setSaving] = useState(false)

  async function save() {
    setSaving(true)
    try {
      await apiPut(`/api/documents/${row.id}/organize`, {
        collection: collection === "none" ? null : collection,
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
    <Dialog open onOpenChange={(open) => !open && !saving && onClose()}>
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
              collection={collection}
              onCollectionChange={setCollection}
              tags={tags}
              onTagsChange={setTags}
              collections={collections.map((c) => c.name)}
              knownTags={knownTags}
            />
          </section>
          <section>
            <h3 className="mb-3 text-sm font-medium">Who can access</h3>
            <SharingSelector value={sharing} onChange={setSharing} domain={domain} />
          </section>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={save} disabled={saving}>
            {saving && <Loader2 className="animate-spin" />} Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
