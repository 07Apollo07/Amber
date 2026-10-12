"use client"

import { useState, useEffect } from "react"
import { FolderOpen, Loader2, Cloud, CloudOff, Folder, FileText, Search, ChevronRight, Home } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { googleSignInUrl } from "@/lib/auth-paths"
import { apiPost } from "@/lib/api"
import { useSession } from "@/lib/session-context"

interface DriveFile {
  id: string
  name: string
  mimeType: string
  size?: string
  webViewLink?: string
  modifiedTime?: string
  synced?: boolean
  document_id?: string | null
  is_folder?: boolean
}

interface Breadcrumb {
  id: string
  name: string
}

export function DrivePickerPanel({ onImported }: { onImported: () => void }) {
  const driveConnected = useSession().drive.connected
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [files, setFiles] = useState<DriveFile[]>([])
  const [selectedIds, setSelectedIds] = useState<Record<string, boolean>>({})
  const [importing, setImporting] = useState(false)
  const [currentFolderId, setCurrentFolderId] = useState<string>("root")
  const [breadcrumbs, setBreadcrumbs] = useState<Breadcrumb[]>([{ id: "root", name: "My Drive" }])
  const [searchQuery, setSearchQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchQuery)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  useEffect(() => {
    if (open) {
      loadDriveFiles(currentFolderId, debouncedQuery)
    }
  }, [open, currentFolderId, debouncedQuery])

  async function loadDriveFiles(folderId: string, q?: string) {
    setLoading(true)
    try {
      let url = `/api/drive/files?folder_id=${encodeURIComponent(folderId)}`
      if (q) {
        url += `&q=${encodeURIComponent(q)}`
      }
      const res = await fetch(url, { credentials: "same-origin" })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail ?? "Failed to load Google Drive files")
      }
      const data = (await res.json()) as {
        files: DriveFile[]
        current_folder_id: string
        current_folder_name: string
      }
      setFiles(data.files ?? [])
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load Google Drive files")
    } finally {
      setLoading(false)
    }
  }

  function handleNavigateFolder(folderId: string, folderName: string) {
    setCurrentFolderId(folderId)
    setBreadcrumbs((prev) => {
      const index = prev.findIndex((b) => b.id === folderId)
      if (index >= 0) {
        return prev.slice(0, index + 1)
      }
      return [...prev, { id: folderId, name: folderName }]
    })
    setSearchQuery("")
  }

  function handleBreadcrumbClick(index: number) {
    const target = breadcrumbs[index]
    setCurrentFolderId(target.id)
    setBreadcrumbs((prev) => prev.slice(0, index + 1))
    setSearchQuery("")
  }

  async function handleImport() {
    const file_ids = Object.entries(selectedIds)
      .filter(([_, selected]) => selected)
      .map(([id]) => id)

    if (file_ids.length === 0) {
      toast.error("Please select at least one file to import")
      return
    }

    setImporting(true)
    try {
      const res = await apiPost("/api/drive/import", { file_ids })
      const data = (await res.json()) as { imported: unknown[]; skipped?: string[] }
      if (data.imported.length > 0) {
        toast.success(`Imported ${data.imported.length} ${data.imported.length === 1 ? "file" : "files"}`)
      }
      if (data.skipped?.length) {
        toast.warning(`Skipped ${data.skipped.length} unsupported ${data.skipped.length === 1 ? "file" : "files"}`, {
          description: data.skipped.join(", "),
        })
      }
      setFiles((prev) =>
        prev.map((f) => (file_ids.includes(f.id) ? { ...f, synced: true } : f))
      )
      setOpen(false)
      setSelectedIds({})
      onImported()
    } catch (err) {
      onImported() // files before the failing one were already added
      toast.error(err instanceof Error ? err.message : "Failed to import files")
    } finally {
      setImporting(false)
    }
  }

  const selectedCount = Object.values(selectedIds).filter(Boolean).length

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

        <Dialog
          open={open}
          onOpenChange={(isOpen) => {
            setOpen(isOpen)
            if (isOpen) {
              setCurrentFolderId("root")
              setBreadcrumbs([{ id: "root", name: "My Drive" }])
              setSearchQuery("")
              loadDriveFiles("root")
            }
          }}
        >
          <DialogTrigger asChild>
            <Button className="mt-4" disabled={!driveConnected}>
              Open Google Drive Picker
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-7xl w-[90vw] h-[85vh] flex flex-col">
            <DialogHeader>
              <DialogTitle>Select Files from Google Drive</DialogTitle>
              <DialogDescription>
                Browse your Google Drive directory structure, select files, and index them into Amber.
              </DialogDescription>
            </DialogHeader>

            {/* Search and Breadcrumbs Toolbar */}
            <div className="flex flex-col gap-3 py-2 border-b">
              <div className="relative">
                <Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
                <Input
                  placeholder="Search files across Google Drive..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>

              {!searchQuery && (
                <div className="flex items-center gap-1 text-sm text-muted-foreground overflow-x-auto py-1">
                  <Home className="size-4 shrink-0" />
                  {breadcrumbs.map((bc, idx) => (
                    <div key={bc.id} className="flex items-center gap-1 shrink-0">
                      {idx > 0 && <ChevronRight className="size-3.5 text-muted-foreground/60" />}
                      <button
                        onClick={() => handleBreadcrumbClick(idx)}
                        className={`hover:text-foreground font-medium transition-colors ${
                          idx === breadcrumbs.length - 1 ? "text-foreground font-semibold" : ""
                        }`}
                      >
                        {bc.name}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* File List / Directory View */}
            <div className="flex-1 overflow-y-auto rounded-lg border p-2 my-2 bg-background/50">
              {loading ? (
                <div className="flex h-64 items-center justify-center">
                  <Loader2 className="size-8 animate-spin text-muted-foreground" />
                </div>
              ) : files.length === 0 ? (
                <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
                  No files or folders found here.
                </div>
              ) : (
                <div className="space-y-1">
                  {files.map((file) => {
                    const isSelected = !!selectedIds[file.id]
                    if (file.is_folder) {
                      return (
                        <div
                          key={file.id}
                          onClick={() => handleNavigateFolder(file.id, file.name)}
                          className="flex cursor-pointer items-center justify-between rounded-md p-3 transition-colors hover:bg-muted/60"
                        >
                          <div className="flex items-center gap-3">
                            <Folder className="size-5 text-amber-500 fill-amber-500/20" />
                            <span className="text-sm font-medium">{file.name}</span>
                          </div>
                          <ChevronRight className="size-4 text-muted-foreground" />
                        </div>
                      )
                    }

                    return (
                      <div
                        key={file.id}
                        onClick={() =>
                          setSelectedIds((prev) => ({ ...prev, [file.id]: !prev[file.id] }))
                        }
                        className="flex cursor-pointer items-center justify-between rounded-md p-3 transition-colors hover:bg-muted/50"
                      >
                        <div className="flex items-center gap-3">
                          <Checkbox
                            checked={isSelected}
                            onCheckedChange={(checked) =>
                              setSelectedIds((prev) => ({ ...prev, [file.id]: checked === true }))
                            }
                            onClick={(e) => e.stopPropagation()}
                          />
                          <FileText className="size-5 text-blue-500" />
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-medium">{file.name}</p>
                              {file.synced ? (
                                <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10px] font-medium text-success" title="Synced in vector store and ready to use">
                                  <Cloud className="size-3" /> Synced in VS
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground" title="Not synced in vector store">
                                  <CloudOff className="size-3" /> Not synced
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground">
                              {file.mimeType.split(".").pop()} {file.size ? `• ${Math.round(Number(file.size) / 1024)} KB` : ""}
                            </p>
                          </div>
                        </div>
                        {file.webViewLink && (
                          <a
                            href={file.webViewLink}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-primary hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            Preview
                          </a>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            <DialogFooter className="flex items-center justify-between border-t pt-3">
              <div className="text-xs text-muted-foreground">
                {selectedCount > 0 ? `${selectedCount} file(s) selected` : "Select files to sync"}
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
                <Button disabled={importing || selectedCount === 0} onClick={handleImport}>
                  {importing && <Loader2 className="mr-2 size-4 animate-spin" />}
                  Add {selectedCount > 0 ? `(${selectedCount})` : ""} to Vector Store
                </Button>
              </div>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {!driveConnected && (
          <a href={googleSignInUrl("/upload", { reconnect: true })} className="mt-2 text-xs text-primary underline-offset-4 hover:underline">
            Reconnect Google Drive first
          </a>
        )}
      </div>
    </div>
  )
}
