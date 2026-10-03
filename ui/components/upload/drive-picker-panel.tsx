"use client"

import { FolderOpen } from "lucide-react"

import { Button } from "@/components/ui/button"
import { googleSignInUrl } from "@/lib/auth-paths"
import { demoAction } from "@/lib/demo"
import { useSession } from "@/lib/session-context"

export function DrivePickerPanel() {
  const driveConnected = useSession().drive.connected

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
        {!driveConnected && (
          <a href={googleSignInUrl("/upload", { reconnect: true })} className="mt-2 text-xs text-primary underline-offset-4 hover:underline">
            Reconnect Google Drive first
          </a>
        )}
      </div>
    </div>
  )
}
