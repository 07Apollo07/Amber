"use client"

import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { apiPut } from "@/lib/api"

import { useAdminData } from "./use-admin-data"

type Indexing = { chunk_size_tokens: number; chunk_overlap_pct: number; max_upload_mb: number }
type SettingsResponse = { indexing: Indexing; limits: Record<keyof Indexing, { min: number; max: number }> }

function Field({ id, label, hint, children }: { id: string; label: string; hint: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5 sm:grid-cols-[220px_1fr] sm:items-start sm:gap-6">
      <div>
        <Label htmlFor={id}>{label}</Label>
        <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
      </div>
      <div className="max-w-xs">{children}</div>
    </div>
  )
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border bg-card/60 p-5">
      <h3 className="font-medium">{title}</h3>
      {note && <p className="mt-1 text-xs text-muted-foreground">{note}</p>}
      <div className="mt-5 space-y-5">{children}</div>
    </section>
  )
}

export function SettingsTab() {
  const { data, error, reload } = useAdminData<SettingsResponse>("/api/admin/settings")
  if (error) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Couldn&apos;t load settings: {error}
      </p>
    )
  }
  if (!data) return <p className="text-sm text-muted-foreground">Loading settings…</p>
  // Keyed by the saved values so the form resets to them after a save.
  return <SettingsForm key={JSON.stringify(data.indexing)} initial={data.indexing} limits={data.limits} onSaved={reload} />
}

function SettingsForm({
  initial,
  limits,
  onSaved,
}: {
  initial: Indexing
  limits: SettingsResponse["limits"]
  onSaved: () => void
}) {
  const [values, setValues] = useState<Record<keyof Indexing, string>>({
    chunk_size_tokens: String(initial.chunk_size_tokens),
    chunk_overlap_pct: String(initial.chunk_overlap_pct),
    max_upload_mb: String(initial.max_upload_mb),
  })
  const [saving, setSaving] = useState(false)

  function input(name: keyof Indexing, id: string, step?: number) {
    return (
      <Input
        id={id}
        type="number"
        required
        min={limits[name].min}
        max={limits[name].max}
        step={step}
        value={values[name]}
        onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))}
      />
    )
  }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    try {
      await apiPut("/api/admin/settings", {
        chunk_size_tokens: Number(values.chunk_size_tokens),
        chunk_overlap_pct: Number(values.chunk_overlap_pct),
        max_upload_mb: Number(values.max_upload_mb),
      })
      toast.success("Settings saved", { description: "Applies to files indexed from now on. Existing files keep their chunks." })
      onSaved()
    } catch (err) {
      toast.error("Couldn't save settings", { description: (err as Error).message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="space-y-6" onSubmit={save}>
      <Section title="Indexing" note="Used when Amber reads, splits and stores a file. Every change is recorded in the audit log.">
        <Field id="chunk-size" label="Chunk size (tokens)" hint="Larger chunks keep more context per passage.">
          {input("chunk_size_tokens", "chunk-size", 50)}
        </Field>
        <Field id="chunk-overlap" label="Chunk overlap (%)" hint="Overlap between neighbouring chunks.">
          {input("chunk_overlap_pct", "chunk-overlap")}
        </Field>
        <Field id="max-upload" label="Max file size (MB)" hint="Larger uploads and Drive imports are rejected.">
          {input("max_upload_mb", "max-upload")}
        </Field>
      </Section>

      <Section title="Answers" note="Not active yet. These apply once answering is built.">
        <Field id="model" label="Answer model" hint="Gemini model used to write answers.">
          <Select defaultValue="flash" disabled>
            <SelectTrigger id="model" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="flash">Gemini Flash (fast)</SelectItem>
              <SelectItem value="pro">Gemini Pro (best quality)</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field id="top-k" label="Passages per answer" hint="How many reranked passages go to the model.">
          <Input id="top-k" type="number" defaultValue={8} disabled />
        </Field>
      </Section>

      <div className="flex justify-end">
        <Button type="submit" disabled={saving}>
          Save settings
        </Button>
      </div>
    </form>
  )
}
