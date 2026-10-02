"use client"

import { useState } from "react"
import { Cloud, HardDrive, Info } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { demoAction, useDemo } from "@/lib/demo"
import { currentUser, uploadQueue, type UploadRow } from "@/lib/mock-data"
import type { Sharing } from "@/lib/types"

import { DrivePickerPanel } from "./drive-picker-panel"
import { Dropzone } from "./dropzone"
import { IngestionTable } from "./ingestion-table"
import { OrganizeFields } from "./organize-fields"
import { SharingSelector } from "./sharing-selector"

export function UploadPage() {
  const { driveConnected } = useDemo()
  const [rows, setRows] = useState<UploadRow[]>(uploadQueue)
  const [sharing, setSharing] = useState<Sharing>({ kind: "private" })
  const [collection, setCollection] = useState("none")
  const [tags, setTags] = useState<string[]>([])

  function enqueue(items: { name: string; sizeBytes: number }[]) {
    const added: UploadRow[] = items.map((item) => ({
      id: crypto.randomUUID(),
      name: item.name,
      sizeBytes: item.sizeBytes,
      status: "queued",
      progress: 0,
      driveUrl: null,
    }))
    setRows((r) => [...added, ...r])
    demoAction(`${added.length} ${added.length === 1 ? "file" : "files"} queued`, "Demo only. Nothing was uploaded.")
  }

  return (
    // DOM order (add files → sharing → status) is the mobile order; on desktop the
    // sharing panel moves into a sticky right column.
    <div className="grid gap-6 lg:grid-cols-[1fr_340px] lg:gap-x-6 lg:gap-y-8">
      <div className="min-w-0 lg:col-start-1">
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
                  Files are saved to your Google Drive in <strong className="font-semibold">Amber Uploads</strong>, then
                  indexed for search.
                </span>
              </div>
            )}
            <Dropzone onFiles={(files) => enqueue(files.map((f) => ({ name: f.name, sizeBytes: f.size })))} />
          </TabsContent>
          <TabsContent value="drive">
            <DrivePickerPanel onIndex={(names) => enqueue(names.map((name) => ({ name, sizeBytes: 0 })))} />
          </TabsContent>
        </Tabs>
      </div>

      <aside className="space-y-6 lg:sticky lg:top-20 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:self-start">
        <section className="rounded-2xl border bg-card/60 p-5">
          <h2 className="font-medium">Who can access</h2>
          <p className="mb-4 text-xs text-muted-foreground">Applies to the next files you add.</p>
          <SharingSelector value={sharing} onChange={setSharing} domain={currentUser.domain} />
        </section>
        <section className="rounded-2xl border bg-card/60 p-5">
          <h2 className="mb-4 font-medium">Organize</h2>
          <OrganizeFields collection={collection} onCollectionChange={setCollection} tags={tags} onTagsChange={setTags} />
        </section>
      </aside>

      <section className="min-w-0 lg:col-start-1">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium">Upload status</h2>
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            onClick={() => setRows((r) => r.filter((row) => row.status !== "ready"))}
          >
            Clear finished
          </Button>
        </div>
        <IngestionTable rows={rows} onRemove={(id) => setRows((r) => r.filter((row) => row.id !== id))} />
      </section>
    </div>
  )
}
