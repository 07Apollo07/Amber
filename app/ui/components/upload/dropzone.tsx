"use client"

import { useRef, useState } from "react"
import { CloudUpload, FolderSync, HardDriveUpload } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { demoAction, useDemo } from "@/lib/demo"
import { cn } from "@/lib/utils"

export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md"]
export const MAX_BYTES = 50 * 1024 * 1024

/**
 * Client-side checks are for fast feedback only. The API re-checks type by magic
 * bytes and enforces the size cap (Phase 4).
 */
export function Dropzone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const { driveConnected, setDriveConnected } = useDemo()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function accept(list: FileList | null) {
    if (!list) return
    const ok: File[] = []
    for (const file of Array.from(list)) {
      const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase()
      if (!ACCEPTED_EXTENSIONS.includes(ext)) {
        toast.error(`${file.name} isn't supported`, { description: `Use ${ACCEPTED_EXTENSIONS.join(", ")}` })
      } else if (file.size > MAX_BYTES) {
        toast.error(`${file.name} is over 50 MB`)
      } else {
        ok.push(file)
      }
    }
    if (ok.length) onFiles(ok)
  }

  if (!driveConnected) {
    return (
      <div className="flex flex-col items-center rounded-2xl border border-dashed border-destructive/40 bg-destructive/5 px-6 py-12 text-center">
        <FolderSync className="mb-3 size-8 text-destructive" />
        <p className="font-medium">Google Drive isn&apos;t connected</p>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          Uploads are saved to your Drive, so reconnect it to upload files.
        </p>
        <Button
          className="mt-4"
          onClick={() => {
            setDriveConnected(true)
            demoAction("Reconnect Google Drive", "Demo: marked Drive as connected.")
          }}
        >
          Reconnect Google Drive
        </Button>
      </div>
    )
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        accept(event.dataTransfer.files)
      }}
      className={cn(
        "flex flex-col items-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors",
        dragging ? "border-primary bg-primary/10" : "border-border bg-card/40 hover:border-primary/40",
      )}
    >
      <span className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-primary/12 text-primary">
        <CloudUpload className="size-6" />
      </span>
      <p className="font-medium">Drag files here</p>
      <p className="mt-1 text-sm text-muted-foreground">PDF, Word, PowerPoint, Excel, TXT or Markdown, up to 50 MB each</p>
      <Button variant="outline" className="mt-4" onClick={() => inputRef.current?.click()}>
        <HardDriveUpload /> Browse files
      </Button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.join(",")}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          accept(event.target.files)
          event.target.value = ""
        }}
      />
    </div>
  )
}
