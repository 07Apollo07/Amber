"use client"

import { useState } from "react"
import { Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
import { demoAction } from "@/lib/demo"

export function DeleteDocumentDialog({ title, inDrive }: { title: string; inDrive: boolean }) {
  const [alsoTrash, setAlsoTrash] = useState(false)
  return (
    <Dialog onOpenChange={(open) => !open && setAlsoTrash(false)}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Delete ${title}`}>
          <Trash2 />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Remove “{title}” from Amber?</DialogTitle>
          <DialogDescription>
            It will no longer appear in search results. The file stays in your Google Drive unless you choose otherwise.
          </DialogDescription>
        </DialogHeader>
        {inDrive && (
          <label htmlFor="also-trash" className="flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm">
            <Checkbox id="also-trash" checked={alsoTrash} onCheckedChange={(v) => setAlsoTrash(v === true)} className="mt-0.5" />
            <span>
              Also move the file to Google Drive trash
              <span className="block text-xs text-muted-foreground">You can restore it from Drive for 30 days.</span>
            </span>
          </label>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <DialogClose asChild>
            <Button
              variant="destructive"
              onClick={() => demoAction(alsoTrash ? "Removed and moved to Drive trash" : "Removed from Amber")}
            >
              Remove
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
