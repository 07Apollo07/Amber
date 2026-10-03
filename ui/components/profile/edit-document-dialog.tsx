"use client"

import { useState } from "react"
import { Pencil } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { OrganizeFields } from "@/components/upload/organize-fields"
import { SharingSelector } from "@/components/upload/sharing-selector"
import { demoAction } from "@/lib/demo"
import { useSession } from "@/lib/session-context"
import type { AmberDocument } from "@/lib/types"

export function EditDocumentDialog({ doc }: { doc: AmberDocument }) {
  const user = useSession()
  const [sharing, setSharing] = useState(doc.sharing)
  const [collection, setCollection] = useState(doc.collection ?? "none")
  const [tags, setTags] = useState(doc.tags)

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Edit ${doc.title}`}>
          <Pencil />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="pr-6">{doc.title}</DialogTitle>
          <DialogDescription>Change who can access this document and how it&apos;s organized.</DialogDescription>
        </DialogHeader>
        <div className="space-y-6">
          <SharingSelector value={sharing} onChange={setSharing} domain={user.domain} />
          <OrganizeFields collection={collection} onCollectionChange={setCollection} tags={tags} onTagsChange={setTags} />
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <DialogClose asChild>
            <Button onClick={() => demoAction("Changes saved", "Demo: Drive sharing was not changed.")}>Save changes</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
