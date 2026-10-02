"use client"

import { useState } from "react"
import { FolderOpen, X } from "lucide-react"

import { FileIcon } from "@/components/app/file-icon"
import { Button } from "@/components/ui/button"
import { demoAction, useDemo } from "@/lib/demo"
import { fileTypeLabel } from "@/lib/format"
import { driveFiles } from "@/lib/mock-data"

export function DrivePickerPanel({ onIndex }: { onIndex: (names: string[]) => void }) {
  const { driveConnected } = useDemo()
  const [picked, setPicked] = useState<typeof driveFiles>([])

  return (
    <div className="rounded-2xl border bg-card/40 p-6">
      <div className="flex flex-col items-center text-center">
        <span className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-info/12 text-info">
          <FolderOpen className="size-6" />
        </span>
        <p className="font-medium">Choose files from Google Drive</p>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">
          Amber only reads the files you pick here. Their Drive sharing decides who can find them in Amber.
        </p>
        <Button
          className="mt-4"
          disabled={!driveConnected}
          onClick={() => {
            demoAction("Google Picker", "Demo: added sample Drive files instead of opening the Picker.")
            setPicked(driveFiles)
          }}
        >
          Open Google Drive Picker
        </Button>
        {!driveConnected && <p className="mt-2 text-xs text-destructive">Reconnect Google Drive from your profile first.</p>}
      </div>

      {picked.length > 0 && (
        <div className="mt-6 border-t pt-4">
          <p className="mb-2 text-sm font-medium">{picked.length} files selected</p>
          <ul className="space-y-1.5">
            {picked.map((file) => (
              <li key={file.id} className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-muted/40">
                <FileIcon type={file.fileType} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{file.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {fileTypeLabel[file.fileType]} · modified {file.modified}
                  </span>
                </span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Remove ${file.title}`}
                  onClick={() => setPicked((p) => p.filter((f) => f.id !== file.id))}
                >
                  <X />
                </Button>
              </li>
            ))}
          </ul>
          <Button
            className="mt-4 w-full"
            onClick={() => {
              onIndex(picked.map((f) => f.title))
              setPicked([])
            }}
          >
            Add {picked.length} {picked.length === 1 ? "file" : "files"} to Amber
          </Button>
        </div>
      )}
    </div>
  )
}
