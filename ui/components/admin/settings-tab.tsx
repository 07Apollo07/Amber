"use client"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { demoAction } from "@/lib/demo"

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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border bg-card/60 p-5">
      <h3 className="mb-5 font-medium">{title}</h3>
      <div className="space-y-5">{children}</div>
    </section>
  )
}

export function SettingsTab() {
  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault()
        demoAction("Settings saved", "Demo only. Changes are versioned and audited once connected.")
      }}
    >
      <Section title="Answers">
        <Field id="model" label="Answer model" hint="Gemini model used to write answers.">
          <Select defaultValue="flash">
            <SelectTrigger id="model" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="flash">Gemini Flash (fast)</SelectItem>
              <SelectItem value="pro">Gemini Pro (best quality)</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field id="reranker" label="Reranker" hint="Orders retrieved passages before answering.">
          <Select defaultValue="cross-encoder">
            <SelectTrigger id="reranker" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="cross-encoder">Local cross-encoder</SelectItem>
              <SelectItem value="llm">Gemini listwise rerank</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field id="top-k" label="Passages per answer" hint="How many reranked passages go to the model.">
          <Input id="top-k" type="number" min={1} max={20} defaultValue={8} />
        </Field>
      </Section>

      <Section title="Indexing">
        <Field id="chunk-size" label="Chunk size (tokens)" hint="Larger chunks keep more context per passage.">
          <Input id="chunk-size" type="number" min={200} max={2000} step={50} defaultValue={800} />
        </Field>
        <Field id="chunk-overlap" label="Chunk overlap (%)" hint="Overlap between neighbouring chunks.">
          <Input id="chunk-overlap" type="number" min={0} max={50} defaultValue={15} />
        </Field>
        <Field id="sync" label="Drive sync interval" hint="How often Drive edits and sharing changes are pulled.">
          <Select defaultValue="15">
            <SelectTrigger id="sync" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="5">Every 5 minutes</SelectItem>
              <SelectItem value="15">Every 15 minutes</SelectItem>
              <SelectItem value="60">Every hour</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field id="max-upload" label="Max upload size (MB)" hint="Per file. The server enforces this too.">
          <Input id="max-upload" type="number" min={1} max={200} defaultValue={50} />
        </Field>
      </Section>

      <div className="flex justify-end gap-2">
        <Button type="reset" variant="ghost">
          Reset
        </Button>
        <Button type="submit">Save settings</Button>
      </div>
    </form>
  )
}
