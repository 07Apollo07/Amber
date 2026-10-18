"use client"

import { useState } from "react"
import { Trash2 } from "lucide-react"
import { toast } from "sonner"

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

export function DeleteDocumentDialog({ title, inDrive, onDelete }: { title: string; inDrive: boolean; onDelete: () => Promise<void> }) {
  const [alsoTrash, setAlsoTrash] = useState(false)
  const [pending, setPending] = useState(false)
  const [open, setOpen] = useState(false)

  async function handleRemove() {
    setPending(true)
    try {
      await onDelete()
      toast.success("Document removed from Amber")
      setOpen(false)
    } catch (err) {
      toast.error("Failed to delete document", {
        description: err instanceof Error ? err.message : "Please try again.",
      })
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setAlsoTrash(false) }}>
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
          <Button variant="outline" onClick={() => setOpen(false)} disabled={pending}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleRemove} disabled={pending}>
            {pending ? "Removing..." : "Remove"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
