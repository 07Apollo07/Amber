"use client"

import { useState } from "react"
import { FolderOpen, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { googleSignInUrl } from "@/lib/auth-paths"
import { apiPost } from "@/lib/api"
import { useSession } from "@/lib/session-context"

// The slice of Google's Picker API this panel uses (https://developers.google.com/drive/picker).
type PickerDoc = { id: string; name: string; mimeType: string }
type PickerResponse = { action: string; docs?: PickerDoc[] }
type PickerBuilder = {
  addView(view: unknown): PickerBuilder
  enableFeature(feature: string): PickerBuilder
  setOAuthToken(token: string): PickerBuilder
  setDeveloperKey(key: string): PickerBuilder
  setAppId(appId: string): PickerBuilder
  setOrigin(origin: string): PickerBuilder
  setCallback(callback: (response: PickerResponse) => void): PickerBuilder
  setTitle(title: string): PickerBuilder
  build(): { setVisible(visible: boolean): void }
}
type DocsView = {
  setIncludeFolders(include: boolean): DocsView
  setSelectFolderEnabled(enabled: boolean): DocsView
  setMimeTypes(types: string): DocsView
  setParent(parentId: string): DocsView
  setOwnedByMe(ownedByMe: boolean): DocsView
  setMode(mode: string): DocsView
  setLabel(label: string): DocsView
}
type PickerApi = {
  PickerBuilder: new () => PickerBuilder
  DocsView: new (viewId?: string) => DocsView
  DocsViewMode: { LIST: string }
  ViewId: { DOCS: string }
  Feature: { MULTISELECT_ENABLED: string }
  Action: { PICKED: string }
}
declare global {
  interface Window {
    gapi?: { load(name: string, callback: () => void): void }
    google?: { picker?: PickerApi }
  }
}

/** Files Amber can index: PDF, Word, PowerPoint, Excel, text, Markdown, and Google Docs, Sheets and Slides. */
const SUPPORTED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/plain",
  "text/markdown",
  "application/vnd.google-apps.document",
  "application/vnd.google-apps.spreadsheet",
  "application/vnd.google-apps.presentation",
]

/** Files sent to /api/drive/import per request, so a large folder never runs into the API's request timeout. */
const IMPORT_BATCH_SIZE = 5

let pickerLoading: Promise<PickerApi> | null = null

/** Loads Google's script and its picker module once. */
function loadPicker(): Promise<PickerApi> {
  pickerLoading ??= new Promise<PickerApi>((resolve, reject) => {
    const fail = () => {
      pickerLoading = null // allow a retry
      reject(new Error("Couldn't load the Google file picker. Check your connection and try again."))
    }
    const ready = () => {
      const picker = window.google?.picker
      if (picker) resolve(picker)
      else fail()
    }
    const loadModule = () => (window.gapi ? window.gapi.load("picker", ready) : fail())
    if (window.gapi) return loadModule()
    const script = document.createElement("script")
    script.src = "https://apis.google.com/js/api.js"
    script.async = true
    script.onload = loadModule
    script.onerror = fail
    document.head.appendChild(script)
  })
  return pickerLoading
}

type PickerToken = { access_token: string; developer_key: string; app_id: string }
type ImportResult = {
  imported: unknown[]
  skipped?: string[]
  failed?: { title: string; error: string }[]
  drive_sync_warning?: string | null
}

function plural(count: number, word: string): string {
  return `${count} ${count === 1 ? word : `${word}s`}`
}

export function DrivePickerPanel({ onImported }: { onImported: () => void }) {
  const { connected: driveConnected } = useSession().drive
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)

  /** Imports the files the user picked (folders can't be picked with drive.file scope). */
  async function importPicked(docs: PickerDoc[]) {
    const fileIds = docs.map((doc) => doc.id)
    const skipped: string[] = []
    const failed: { title: string; error: string }[] = []
    let imported = 0
    let syncWarning: string | null = null
    try {
      setProgress({ done: 0, total: fileIds.length })
      for (let start = 0; start < fileIds.length; start += IMPORT_BATCH_SIZE) {
        const batch = fileIds.slice(start, start + IMPORT_BATCH_SIZE)
        try {
          const res = await apiPost("/api/drive/import", { file_ids: batch })
          const data = (await res.json()) as ImportResult
          imported += data.imported.length
          skipped.push(...(data.skipped ?? []))
          failed.push(...(data.failed ?? []))
          syncWarning = data.drive_sync_warning ?? syncWarning
        } catch (err) {
          // A failed batch shouldn't stop the rest.
          const error = err instanceof Error ? err.message : "Failed to import files"
          failed.push(...batch.map((id) => ({ title: id, error })))
        }
        setProgress({ done: Math.min(start + batch.length, fileIds.length), total: fileIds.length })
        onImported() // show files as they finish, not only at the end
      }

      if (imported > 0) toast.success(`Imported ${plural(imported, "file")}`)
      if (failed.length) {
        toast.error(`${plural(failed.length, "file")} couldn't be imported`, {
          description: "Open the file in Manage Files to see the full error.",
        })
      }
      if (skipped.length) {
        toast.warning(`Skipped ${plural(skipped.length, "unsupported file")}`, {
          description: skipped.slice(0, 10).join(", ") + (skipped.length > 10 ? `, and ${skipped.length - 10} more` : ""),
        })
      }
      if (syncWarning) {
        toast.warning("Drive permission sync couldn't be started", { description: syncWarning, duration: 12000 })
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to import files")
    } finally {
      onImported() // also covers files added before a failure
      setProgress(null)
      setBusy(false)
    }
  }

  async function openPicker() {
    setBusy(true)
    try {
      const [picker, tokenRes] = await Promise.all([loadPicker(), apiPost("/api/drive/picker-token")])
      const token = (await tokenRes.json()) as PickerToken

      // Show only files (not folders) in the picker. Folders are still shown for navigation via setIncludeFolders(true).
      const mimeTypes = SUPPORTED_MIME_TYPES.join(",")
      const view = (label: string) =>
        new picker.DocsView(picker.ViewId.DOCS)
          .setLabel(label)
          .setMode(picker.DocsViewMode.LIST)
          .setIncludeFolders(true)      // allows browsing into folders
          .setSelectFolderEnabled(false) // folder selection requires drive.readonly scope (not requested)
          .setMimeTypes(mimeTypes)
      const myDrive = view("My Drive").setParent("root")
      const sharedWithMe = view("Shared with me").setOwnedByMe(false)

      new picker.PickerBuilder()
        .setTitle("Choose files for Amber")
        .addView(myDrive)
        .addView(sharedWithMe)
        .enableFeature(picker.Feature.MULTISELECT_ENABLED)
        .setOAuthToken(token.access_token)
        .setDeveloperKey(token.developer_key)
        .setAppId(token.app_id)
        .setOrigin(window.location.origin)
        .setCallback((response) => {
          if (response.action === picker.Action.PICKED && response.docs?.length) {
            void importPicked(response.docs)
          } else if (response.action === picker.Action.PICKED || response.action === "cancel") {
            setBusy(false)
          }
        })
        .build()
        .setVisible(true)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't open the Google file picker")
      setBusy(false)
    }
  }

  return (
    <div className="rounded-2xl border bg-card/40 p-6">
      <div className="flex flex-col items-center text-center">
        <span className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-info/12 text-info">
          <FolderOpen className="size-6" />
        </span>
        <p className="font-medium">Choose files from Google Drive</p>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">
          Browse your Drive folder by folder and select the files you want. Multi-select is supported.
          Their Drive sharing decides who can find them in Amber.
        </p>
        <Button className="mt-4" disabled={!driveConnected || busy} onClick={openPicker}>
          {busy && <Loader2 className="animate-spin" />}
          {progress ? `Importing ${progress.done} of ${progress.total}…` : "Open Google Drive"}
        </Button>
        {!driveConnected && (
          <a href={googleSignInUrl("/upload", { reconnect: true })} className="mt-2 text-xs text-primary underline-offset-4 hover:underline">
            Connect Google Drive first
          </a>
        )}
      </div>
    </div>
  )
}
