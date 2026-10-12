"use client"

import { useCallback, useEffect, useState } from "react"
import { Cloud, HardDrive, Info } from "lucide-react"
import { toast } from "sonner"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiUpload } from "@/lib/api"
import { useSession } from "@/lib/session-context"
import type { Collection, IngestionStatus, Sharing, UploadRow } from "@/lib/types"

import { DocumentSettingsDialog } from "./document-settings-dialog"
import { DrivePickerPanel } from "./drive-picker-panel"
import { Dropzone } from "./dropzone"
import { ManageFiles } from "./manage-files"
import { OrganizeFields } from "./organize-fields"
import { SharingSelector } from "./sharing-selector"

/** A document as returned by GET /api/documents/mine. */
type ApiDocument = {
  id: string
  title: string
  status: string
  status_message: string | null
  file_size_bytes: number
  drive_url: string | null
  tags: string[]
  collection: string | null
  collection_id: string | null
  sharing: Sharing
}

const STATUS: Record<string, IngestionStatus> = {
  queued: "queued",
  saving_to_drive: "saving_to_drive",
  parsing: "parsing",
  indexing: "embedding",
  indexed: "ready",
  failed: "failed",
}

async function fetchMine() {
  const res = await fetch("/api/documents/mine", { credentials: "same-origin" })
  if (!res.ok) throw new Error(`Request failed (${res.status})`)
  return (await res.json()) as { documents: ApiDocument[]; collections: Collection[]; tags: string[] }
}

function toRow(doc: ApiDocument): UploadRow {
  const status = STATUS[doc.status] ?? "queued"
  return {
    id: doc.id,
    name: doc.title,
    sizeBytes: doc.file_size_bytes,
    status,
    progress: status === "ready" ? 100 : 60,
    error: status === "failed" ? (doc.status_message ?? "Indexing failed") : undefined,
    driveUrl: doc.drive_url,
    saved: true,
    tags: doc.tags,
    collection: doc.collection,
    collectionId: doc.collection_id,
    sharing: doc.sharing,
  }
}

export function UploadPage() {
  const user = useSession()
  const driveConnected = user.drive.connected
  // Every document the user owns, from the API.
  const [saved, setSaved] = useState<UploadRow[]>([])
  // Uploads still travelling to the API, or that failed before a document existed.
  const [pending, setPending] = useState<UploadRow[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [knownTags, setKnownTags] = useState<string[]>([])
  const [loaded, setLoaded] = useState(false)
  const [managing, setManaging] = useState<UploadRow | null>(null)

  // Settings for the next files added.
  const [sharing, setSharing] = useState<Sharing>({ kind: "private" })
  const [collection, setCollection] = useState("none")
  const [tags, setTags] = useState<string[]>([])

  const refresh = useCallback(async () => {
    try {
      const data = await fetchMine()
      setSaved(data.documents.map(toRow))
      setCollections(data.collections)
      setKnownTags(data.tags)
    } catch {
      toast.error("Couldn't load your documents")
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchMine()
      .then((data) => {
        if (cancelled) return
        setSaved(data.documents.map(toRow))
        setCollections(data.collections)
        setKnownTags(data.tags)
      })
      .catch(() => !cancelled && toast.error("Couldn't load your documents"))
      .finally(() => !cancelled && setLoaded(true))
    return () => {
      cancelled = true
    }
  }, [])

  // Keep checking while something is still being indexed (for example after a refresh mid-import).
  const busy = saved.some((r) => r.status !== "ready" && r.status !== "failed")
  useEffect(() => {
    if (!busy) return
    const timer = setInterval(() => void refresh(), 3000)
    return () => clearInterval(timer)
  }, [busy, refresh])

  async function uploadFiles(files: File[]) {
    const selectedCollection = collection === "none" ? "" : collection
    await Promise.all(
      files.map(async (file) => {
        const id = `local-${crypto.randomUUID()}`
        setPending((p) => [
          {
            id,
            name: file.name,
            sizeBytes: file.size,
            status: "saving_to_drive",
            progress: 30,
            driveUrl: null,
            saved: false,
            tags,
            collection: selectedCollection || null,
            collectionId: null,
            sharing,
          },
          ...p,
        ])
        const form = new FormData()
        form.append("file", file)
        form.append("sharing", sharing.kind)
        if (sharing.kind === "people") form.append("emails", sharing.emails.join(","))
        form.append("collection", selectedCollection)
        form.append("tags", tags.join(","))
        try {
          await apiUpload("/api/documents/upload", form)
          await refresh()
          setPending((p) => p.filter((r) => r.id !== id))
        } catch (err) {
          const error = err instanceof Error ? err.message : "Upload failed"
          setPending((p) => p.map((r) => (r.id === id ? { ...r, status: "failed", error } : r)))
        }
      }),
    )
  }

  return (
    // On mobile the add-files and sharing panels come first; on desktop they form a right-hand column
    // next to Manage Files.
    <div className="grid gap-6 lg:grid-cols-[1fr_380px] lg:items-start">
      <aside className="space-y-6 lg:sticky lg:top-20 lg:col-start-2 lg:row-start-1 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pr-1">
        <section aria-label="Add files">
          <Tabs defaultValue="computer">
            <TabsList className="mb-4">
              <TabsTrigger value="computer">
                <HardDrive /> From computer
              </TabsTrigger>
              <TabsTrigger value="drive">
                <Cloud /> From Google Drive
              </TabsTrigger>
            </TabsList>
            <TabsContent value="computer" className="space-y-3">
              {driveConnected && (
                <div className="flex items-start gap-2 rounded-xl border border-info/25 bg-info/8 px-3 py-2.5 text-sm">
                  <Info className="mt-0.5 size-4 shrink-0 text-info" />
                  <span>
                    Files are saved to your Google Drive in <strong className="font-semibold">Amber Uploads</strong>,
                    then indexed for search.
                  </span>
                </div>
              )}
              <Dropzone onFiles={uploadFiles} />
            </TabsContent>
            <TabsContent value="drive">
              <DrivePickerPanel
                collection={collection === "none" ? null : collection}
                tags={tags}
                onImported={() => void refresh()}
              />
            </TabsContent>
          </Tabs>
        </section>
        <section className="rounded-2xl border bg-card/60 p-5">
          <h2 className="font-medium">Who can access</h2>
          <p className="mb-4 text-xs text-muted-foreground">
            Applies to files you upload from your computer. Files from Google Drive keep their Drive sharing. Change
            either later with Manage.
          </p>
          <SharingSelector value={sharing} onChange={setSharing} domain={user.domain} />
        </section>
        <section className="rounded-2xl border bg-card/60 p-5">
          <h2 className="mb-1 font-medium">Organize</h2>
          <p className="mb-4 text-xs text-muted-foreground">Applies to the next files you add.</p>
          <OrganizeFields
            collection={collection}
            onCollectionChange={setCollection}
            tags={tags}
            onTagsChange={setTags}
            collections={collections.map((c) => c.name)}
            knownTags={knownTags}
          />
        </section>
      </aside>

      <section className="min-w-0 lg:col-start-1 lg:row-start-1" aria-labelledby="manage-files-heading">
        <h2 id="manage-files-heading" className="mb-3 text-sm font-medium">
          Manage Files
        </h2>
        {loaded ? (
          <ManageFiles
            pending={pending}
            saved={saved}
            collections={collections}
            domain={user.domain}
            onManage={setManaging}
            onRemovePending={(id) => setPending((p) => p.filter((row) => row.id !== id))}
            onChanged={() => void refresh()}
          />
        ) : (
          <p className="text-sm text-muted-foreground">Loading your documents…</p>
        )}
      </section>

      {managing && (
        <DocumentSettingsDialog
          row={managing}
          domain={user.domain}
          collections={collections}
          knownTags={knownTags}
          onClose={() => setManaging(null)}
          onSaved={() => void refresh()}
        />
      )}
    </div>
  )
}
