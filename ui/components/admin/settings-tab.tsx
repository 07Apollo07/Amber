"use client"

import { useState } from "react"
import { AlertTriangle, Database, MessageSquareText, Mic, RotateCcw } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { exactTime, timeAgo } from "@/lib/admin-activity"
import { apiPut } from "@/lib/api"

import { useAdminData } from "./use-admin-data"

type Limits<K extends string> = Partial<Record<K, { min: number; max: number }>>
type Edited = { at: string; by: { name: string | null; email: string } | null } | null
type Section<V, O = undefined> = { values: V; defaults: V; limits: Limits<Extract<keyof V, string>>; edited: Edited; options: O }

type Indexing = { chunk_size_tokens: number; chunk_overlap_pct: number; max_upload_mb: number }
type Chat = { default_model: string | null; passages_per_search: number; web_search_enabled: boolean }
type Voice = { enabled: boolean; voice: string | null; max_session_minutes: number }
type ChatOptions = {
  models: string[]
  models_error: string | null
  model_choice_available: boolean
  server_default_model: string
}
type VoiceOptions = { voices: string[]; server_default_voice: string; configured: boolean; server_max_minutes: number }
type SettingsResponse = {
  indexing: Section<Indexing>
  chat: Section<Chat, ChatOptions>
  voice: Section<Voice, VoiceOptions>
}

const SERVER_DEFAULT = "__server_default__" // Radix Select can't use "" as a value

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string
  label: string
  hint: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-1.5 sm:grid-cols-[240px_1fr] sm:items-start sm:gap-6">
      <div>
        <Label htmlFor={id}>{label}</Label>
        <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
      </div>
      <div className="max-w-sm">{children}</div>
    </div>
  )
}

function lastChanged(edited: Edited) {
  if (!edited) return "Using the default settings. Not changed yet."
  const who = edited.by ? edited.by.name || edited.by.email : "someone"
  return (
    <>
      Last changed by {who},{" "}
      <time dateTime={edited.at} title={exactTime(edited.at)}>
        {timeAgo(edited.at)}
      </time>
    </>
  )
}

function same<V>(a: V, b: V) {
  return JSON.stringify(a) === JSON.stringify(b)
}

/** One settings card with its own Save. `toBody` turns the form strings back into the API's values. */
function SettingsSection<V extends Record<string, unknown>>({
  section,
  title,
  icon: Icon,
  description,
  initial,
  defaults,
  edited,
  toForm,
  toBody,
  savedMessage,
  onSaved,
  children,
}: {
  section: "indexing" | "chat" | "voice"
  title: string
  icon: React.ComponentType<{ className?: string }>
  description: string
  initial: V
  defaults: V
  edited: Edited
  toForm: (v: V) => Record<string, string | boolean>
  toBody: (form: Record<string, string | boolean>) => V
  savedMessage: string
  onSaved: () => void
  children: (form: Record<string, string | boolean>, set: (name: string, value: string | boolean) => void) => React.ReactNode
}) {
  const [form, setForm] = useState(() => toForm(initial))
  const [saving, setSaving] = useState(false)
  const dirty = !same(toForm(initial), form)
  const isDefault = same(toForm(defaults), form)

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    try {
      await apiPut(`/api/admin/settings/${section}`, toBody(form))
      toast.success(`${title} settings saved`, { description: savedMessage })
      onSaved()
    } catch (err) {
      toast.error(`Couldn't save ${title.toLowerCase()} settings`, { description: (err as Error).message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={save} className="rounded-2xl border bg-card/60 p-5" aria-labelledby={`${section}-title`}>
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
          <Icon className="size-4" />
        </span>
        <div className="min-w-0">
          <h3 id={`${section}-title`} className="font-medium">
            {title}
          </h3>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
      </div>
      <div className="mt-5 space-y-5">{children(form, (name, value) => setForm((f) => ({ ...f, [name]: value })))}</div>
      <div className="mt-6 flex flex-wrap items-center gap-3 border-t pt-4">
        <p className="mr-auto text-xs text-muted-foreground">{lastChanged(edited)}</p>
        {dirty && <span className="text-xs text-warning">Unsaved changes</span>}
        <Button type="button" variant="ghost" size="sm" disabled={isDefault || saving} onClick={() => setForm(toForm(defaults))}>
          <RotateCcw /> Reset to defaults
        </Button>
        {dirty && (
          <Button type="button" variant="outline" size="sm" disabled={saving} onClick={() => setForm(toForm(initial))}>
            Discard
          </Button>
        )}
        <Button type="submit" size="sm" disabled={!dirty || saving}>
          {saving && <Spinner />} Save
        </Button>
      </div>
    </form>
  )
}

function NumberInput({
  id,
  value,
  limits,
  step,
  onChange,
  disabled,
}: {
  id: string
  value: string
  limits?: { min: number; max: number }
  step?: number
  onChange: (value: string) => void
  disabled?: boolean
}) {
  return (
    <Input
      id={id}
      type="number"
      inputMode="numeric"
      required
      min={limits?.min}
      max={limits?.max}
      step={step}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

function range(limits?: { min: number; max: number }) {
  return limits ? ` (${limits.min}–${limits.max})` : ""
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
  if (!data) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner /> Loading settings…
      </p>
    )
  }

  const { chat, voice, indexing } = data
  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm text-muted-foreground">
        Changes apply straight away for everyone and are recorded in the audit log.
      </p>

      {/* Keyed by the saved values so each form resets to them after a save. */}
      <SettingsSection<Chat>
        key={`chat-${JSON.stringify(chat.values)}`}
        section="chat"
        title="Chat"
        icon={MessageSquareText}
        description="How Amber answers questions in chat."
        initial={chat.values}
        defaults={chat.defaults}
        edited={chat.edited}
        savedMessage="New chat messages use these settings."
        onSaved={reload}
        toForm={(v) => ({
          default_model: v.default_model ?? SERVER_DEFAULT,
          passages_per_search: String(v.passages_per_search),
          web_search_enabled: v.web_search_enabled,
        })}
        toBody={(f) => ({
          default_model: f.default_model === SERVER_DEFAULT ? null : String(f.default_model),
          passages_per_search: Number(f.passages_per_search),
          web_search_enabled: Boolean(f.web_search_enabled),
        })}
      >
        {(form, set) => {
          const current = String(form.default_model)
          const offered = new Set(chat.options.models)
          return (
            <>
              <Field
                id="default-model"
                label="Default model"
                hint={
                  chat.options.model_choice_available
                    ? "Used when someone doesn't pick a model in chat. People can still choose another."
                    : "Model choice needs a LiteLLM proxy (AMBER_LITELLM_BASE_URL)."
                }
              >
                <Select
                  value={current}
                  onValueChange={(value) => set("default_model", value)}
                  disabled={!chat.options.model_choice_available}
                >
                  <SelectTrigger id="default-model" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={SERVER_DEFAULT}>Server default ({chat.options.server_default_model})</SelectItem>
                    {current !== SERVER_DEFAULT && !offered.has(current) && (
                      <SelectItem value={current}>{current} (no longer offered)</SelectItem>
                    )}
                    {chat.options.models.map((model) => (
                      <SelectItem key={model} value={model}>
                        {model}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {chat.options.models_error && (
                  <p className="mt-1.5 flex items-center gap-1 text-xs text-warning">
                    <AlertTriangle className="size-3.5" /> Couldn&apos;t load the model list: {chat.options.models_error}
                  </p>
                )}
                {current !== SERVER_DEFAULT && !offered.has(current) && !chat.options.models_error && (
                  <p className="mt-1.5 flex items-center gap-1 text-xs text-warning">
                    <AlertTriangle className="size-3.5" /> The proxy no longer offers this model, so chat uses the server
                    default.
                  </p>
                )}
              </Field>
              <Field
                id="passages"
                label="Passages per search"
                hint={`How many passages Amber reads from your documents each time it searches${range(chat.limits.passages_per_search)}. More gives fuller answers but is slower.`}
              >
                <NumberInput
                  id="passages"
                  value={String(form.passages_per_search)}
                  limits={chat.limits.passages_per_search}
                  onChange={(value) => set("passages_per_search", value)}
                />
              </Field>
              <Field
                id="web-search"
                label="Web search"
                hint="Lets Amber look things up on the public web when your documents don't cover a question."
              >
                <div className="flex items-center gap-3 pt-0.5">
                  <Switch
                    id="web-search"
                    checked={Boolean(form.web_search_enabled)}
                    onCheckedChange={(checked) => set("web_search_enabled", checked)}
                  />
                  <span className="text-sm">{form.web_search_enabled ? "On" : "Off"}</span>
                </div>
              </Field>
            </>
          )
        }}
      </SettingsSection>

      <SettingsSection<Voice>
        key={`voice-${JSON.stringify(voice.values)}`}
        section="voice"
        title="Opal voice"
        icon={Mic}
        description="Opal is the voice sidekick beside each chat."
        initial={voice.values}
        defaults={voice.defaults}
        edited={voice.edited}
        savedMessage="Applies to voice sessions started from now on."
        onSaved={reload}
        toForm={(v) => ({
          enabled: v.enabled,
          voice: v.voice ?? SERVER_DEFAULT,
          max_session_minutes: String(v.max_session_minutes),
        })}
        toBody={(f) => ({
          enabled: Boolean(f.enabled),
          voice: f.voice === SERVER_DEFAULT ? null : String(f.voice),
          max_session_minutes: Number(f.max_session_minutes),
        })}
      >
        {(form, set) => (
          <>
            {!voice.options.configured && (
              <p className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                <span>
                  Opal isn&apos;t set up on this server, so it stays off whatever you choose here. Add
                  AMBER_GEMINI_LIVE_API_KEY (or AMBER_GEMINI_API_KEY) and AMBER_GEMINI_LIVE_MODEL to turn it on.
                </span>
              </p>
            )}
            <Field id="voice-enabled" label="Opal voice" hint="When off, the Talk to Opal button is unavailable for everyone.">
              <div className="flex items-center gap-3 pt-0.5">
                <Switch id="voice-enabled" checked={Boolean(form.enabled)} onCheckedChange={(checked) => set("enabled", checked)} />
                <span className="text-sm">{form.enabled ? "On" : "Off"}</span>
              </div>
            </Field>
            <Field id="voice" label="Voice" hint="How Opal sounds.">
              <Select value={String(form.voice)} onValueChange={(value) => set("voice", value)}>
                <SelectTrigger id="voice" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={SERVER_DEFAULT}>Server default ({voice.options.server_default_voice})</SelectItem>
                  {voice.options.voices.map((v) => (
                    <SelectItem key={v} value={v}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field
              id="session-minutes"
              label="Session length limit (minutes)"
              hint={`A voice session ends after this long${range(voice.limits.max_session_minutes)}. People can start a new one.`}
            >
              <NumberInput
                id="session-minutes"
                value={String(form.max_session_minutes)}
                limits={voice.limits.max_session_minutes}
                onChange={(value) => set("max_session_minutes", value)}
              />
              {Number(form.max_session_minutes) > voice.options.server_max_minutes && (
                <p className="mt-1.5 flex items-center gap-1 text-xs text-warning">
                  <AlertTriangle className="size-3.5" /> The server caps sessions at {voice.options.server_max_minutes}{" "}
                  minutes, so that limit applies.
                </p>
              )}
            </Field>
          </>
        )}
      </SettingsSection>

      <SettingsSection<Indexing>
        key={`indexing-${JSON.stringify(indexing.values)}`}
        section="indexing"
        title="Indexing"
        icon={Database}
        description="How Amber reads, splits and stores files."
        initial={indexing.values}
        defaults={indexing.defaults}
        edited={indexing.edited}
        savedMessage="Applies to files indexed from now on. Existing files keep their passages."
        onSaved={reload}
        toForm={(v) => ({
          chunk_size_tokens: String(v.chunk_size_tokens),
          chunk_overlap_pct: String(v.chunk_overlap_pct),
          max_upload_mb: String(v.max_upload_mb),
        })}
        toBody={(f) => ({
          chunk_size_tokens: Number(f.chunk_size_tokens),
          chunk_overlap_pct: Number(f.chunk_overlap_pct),
          max_upload_mb: Number(f.max_upload_mb),
        })}
      >
        {(form, set) => (
          <>
            <Field
              id="chunk-size"
              label="Passage size (tokens)"
              hint={`Larger passages keep more context together${range(indexing.limits.chunk_size_tokens)}.`}
            >
              <NumberInput
                id="chunk-size"
                step={50}
                value={String(form.chunk_size_tokens)}
                limits={indexing.limits.chunk_size_tokens}
                onChange={(value) => set("chunk_size_tokens", value)}
              />
            </Field>
            <Field
              id="chunk-overlap"
              label="Passage overlap (%)"
              hint={`How much neighbouring passages share, so ideas aren't cut in half${range(indexing.limits.chunk_overlap_pct)}.`}
            >
              <NumberInput
                id="chunk-overlap"
                value={String(form.chunk_overlap_pct)}
                limits={indexing.limits.chunk_overlap_pct}
                onChange={(value) => set("chunk_overlap_pct", value)}
              />
            </Field>
            <Field
              id="max-upload"
              label="Max file size (MB)"
              hint={`Larger uploads and Drive imports are rejected${range(indexing.limits.max_upload_mb)}.`}
            >
              <NumberInput
                id="max-upload"
                value={String(form.max_upload_mb)}
                limits={indexing.limits.max_upload_mb}
                onChange={(value) => set("max_upload_mb", value)}
              />
            </Field>
          </>
        )}
      </SettingsSection>
    </div>
  )
}
