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
  setCallback(callback: (response: PickerResponse) => void): PickerBuilder
  setTitle(title: string): PickerBuilder
  build(): { setVisible(visible: boolean): void }
}
type DocsView = {
  setIncludeFolders(include: boolean): DocsView
  setSelectFolderEnabled(enabled: boolean): DocsView
  setMimeTypes(types: string): DocsView
}
type PickerApi = {
  PickerBuilder: new () => PickerBuilder
  DocsView: new (viewId?: string) => DocsView
  ViewId: { DOCS: string }
  Feature: { MULTISELECT_ENABLED: string; SUPPORT_DRIVES: string }
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
].join(",")

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

export function DrivePickerPanel({ onImported }: { onImported: () => void }) {
  const driveConnected = useSession().drive.connected
  const [busy, setBusy] = useState(false)

  async function importFiles(fileIds: string[]) {
    try {
      const res = await apiPost("/api/drive/import", { file_ids: fileIds })
      const data = (await res.json()) as {
        imported: unknown[]
        skipped?: string[]
        failed?: { title: string; error: string }[]
      }
      if (data.imported.length > 0) {
        toast.success(`Imported ${data.imported.length} ${data.imported.length === 1 ? "file" : "files"}`)
      }
      if (data.failed?.length) {
        toast.error(`${data.failed.length} ${data.failed.length === 1 ? "file" : "files"} couldn't be imported`, {
          description: "Open the file in Manage Files to see the full error.",
        })
      }
      if (data.skipped?.length) {
        toast.warning(`Skipped ${data.skipped.length} unsupported ${data.skipped.length === 1 ? "file" : "files"}`, {
          description: data.skipped.join(", "),
        })
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to import files")
    } finally {
      onImported() // also covers files added before a failure
      setBusy(false)
    }
  }

  async function openPicker() {
    setBusy(true)
    try {
      const [picker, tokenRes] = await Promise.all([loadPicker(), apiPost("/api/drive/picker-token")])
      const token = (await tokenRes.json()) as PickerToken

      const myDrive = new picker.DocsView(picker.ViewId.DOCS)
        .setIncludeFolders(false)
        .setSelectFolderEnabled(false)
        .setMimeTypes(SUPPORTED_MIME_TYPES)

      new picker.PickerBuilder()
        .setTitle("Choose files for Amber")
        .addView(myDrive)
        .enableFeature(picker.Feature.MULTISELECT_ENABLED)
        .enableFeature(picker.Feature.SUPPORT_DRIVES)
        .setOAuthToken(token.access_token)
        .setDeveloperKey(token.developer_key)
        .setAppId(token.app_id)
        .setCallback((response) => {
          if (response.action === picker.Action.PICKED && response.docs?.length) {
            void importFiles(response.docs.map((doc) => doc.id))
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
          Amber can only open the files you pick here, plus the ones it saves for you. Their Drive sharing decides who can
          find them in Amber.
        </p>
        <Button className="mt-4" disabled={!driveConnected || busy} onClick={openPicker}>
          {busy && <Loader2 className="animate-spin" />}
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
