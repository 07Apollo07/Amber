"use client"

import { FolderOpen } from "lucide-react"

import { Button } from "@/components/ui/button"
import { demoAction, useDemo } from "@/lib/demo"

export function DrivePickerPanel() {
  const { driveConnected } = useDemo()

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
          onClick={() => demoAction("Google Picker", "The Drive Picker is wired up in Phase 7.")}
        >
          Open Google Drive Picker
        </Button>
        {!driveConnected && <p className="mt-2 text-xs text-destructive">Reconnect Google Drive from your profile first.</p>}
      </div>
    </div>
  )
}
