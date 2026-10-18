"use client"

import { useEffect, useRef, useState } from "react"
import { LoaderCircle, Mic, MicOff, PhoneOff, Volume2 } from "lucide-react"

import { Persona, type PersonaState } from "@/components/ai-elements/persona"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type LiveConfig = {
  enabled: boolean
  model: string | null
}

type SidekickLine = {
  id: string
  role: "you" | "opal"
  text: string
}

type LiveSidekickProps = {
  context: string
  draft: string
  onDraftChange: (draft: string) => void
}

const INPUT_SAMPLE_RATE = 16000 // Gemini Live takes 16 kHz PCM16 and returns 24 kHz
const OUTPUT_SAMPLE_RATE = 24000
const MAX_DRAFT_LENGTH = 2000

function liveSocketUrl(): string {
  const apiOrigin =
    process.env.NEXT_PUBLIC_AMBER_API_ORIGIN ||
    (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : window.location.origin)
  const url = new URL("/api/agent/live", apiOrigin)
  if (process.env.NODE_ENV === "development") url.hostname = window.location.hostname
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  return url.toString()
}

function encodePcm16(samples: Float32Array, sampleRate: number): string {
  const targetLength = Math.round((samples.length * INPUT_SAMPLE_RATE) / sampleRate)
  const bytes = new Uint8Array(targetLength * 2)
  const view = new DataView(bytes.buffer)

  for (let index = 0; index < targetLength; index += 1) {
    const sourcePosition = (index * sampleRate) / INPUT_SAMPLE_RATE
    const lower = Math.floor(sourcePosition)
    const upper = Math.min(lower + 1, samples.length - 1)
    const fraction = sourcePosition - lower
    const sample = samples[lower] * (1 - fraction) + samples[upper] * fraction
    const value = Math.max(-1, Math.min(1, sample))
    view.setInt16(index * 2, value < 0 ? value * 0x8000 : value * 0x7fff, true)
  }

  let binary = ""
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

function errorMessage(value: unknown): string {
  if (value instanceof Error && value.message) return value.message
  return "The voice connection could not be started."
}

function stringField(event: object, key: string): string | null {
  const value = (event as Record<string, unknown>)[key]
  return typeof value === "string" ? value : null
}

export function LiveSidekick({ context, draft, onDraftChange }: LiveSidekickProps) {
  const [config, setConfig] = useState<LiveConfig | null>(null)
  const [configError, setConfigError] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [connected, setConnected] = useState(false)
  const [muted, setMuted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lines, setLines] = useState<SidekickLine[]>([])
  const [state, setState] = useState<PersonaState>("idle")
  const draftRef = useRef(draft)
  const contextRef = useRef(context)
  const mutedRef = useRef(false)
  const socketRef = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const captureContextRef = useRef<AudioContext | null>(null)
  const playbackContextRef = useRef<AudioContext | null>(null)
  const captureNodesRef = useRef<AudioNode[]>([])
  const playingRef = useRef<Set<AudioBufferSourceNode>>(new Set())
  const nextPlaybackTimeRef = useRef(0)
  const userLineIdRef = useRef<string | null>(null)
  const assistantLineIdRef = useRef<string | null>(null)
  const sentContextRef = useRef("")

  useEffect(() => {
    draftRef.current = draft
  }, [draft])

  useEffect(() => {
    contextRef.current = context
  }, [context])

  useEffect(() => {
    const controller = new AbortController()
    async function loadConfig() {
      try {
        const response = await fetch("/api/agent/live/config", {
          cache: "no-store",
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(`Could not load voice settings (${response.status})`)
        const value: unknown = await response.json()
        if (
          typeof value !== "object" ||
          value === null ||
          !("enabled" in value) ||
          typeof value.enabled !== "boolean" ||
          !("model" in value) ||
          (value.model !== null && typeof value.model !== "string")
        ) {
          throw new Error("The voice settings response is invalid")
        }
        setConfig({ enabled: value.enabled, model: value.model })
      } catch (loadError) {
        if (!controller.signal.aborted) {
          console.error("Failed to load Opal voice settings", loadError)
          setConfigError(true)
        }
      }
    }

    void loadConfig()
    return () => controller.abort()
  }, [])

  function stopPlayback() {
    for (const source of playingRef.current) {
      source.onended = null
      try {
        source.stop()
      } catch {
        // already stopped
      }
    }
    playingRef.current.clear()
    nextPlaybackTimeRef.current = 0
  }

  function closeAudio() {
    stopPlayback()
    for (const node of captureNodesRef.current) node.disconnect()
    captureNodesRef.current = []
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    void captureContextRef.current?.close()
    void playbackContextRef.current?.close()
    captureContextRef.current = null
    playbackContextRef.current = null
  }

  function resetSession() {
    closeAudio()
    userLineIdRef.current = null
    assistantLineIdRef.current = null
    sentContextRef.current = ""
    mutedRef.current = false
    setMuted(false)
    setConnected(false)
    setConnecting(false)
    setState("idle")
  }

  function stopSession() {
    const socket = socketRef.current
    socketRef.current = null
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000)
    resetSession()
  }

  useEffect(() => () => {
    const socket = socketRef.current
    socketRef.current = null
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000)
    closeAudio()
  }, [])

  function addLine(role: SidekickLine["role"], text: string) {
    const id = crypto.randomUUID()
    setLines((current) => [...current.slice(-7), { id, role, text }])
    return id
  }

  function appendTranscript(role: SidekickLine["role"], delta: string) {
    if (!delta) return
    const ref = role === "opal" ? assistantLineIdRef : userLineIdRef
    const id = ref.current ?? crypto.randomUUID()
    ref.current = id
    setLines((current) => {
      if (!current.some((line) => line.id === id)) return [...current.slice(-7), { id, role, text: delta.trimStart() }]
      return current.map((line) => (line.id === id ? { ...line, text: line.text + delta } : line))
    })
  }

  function send(event: Record<string, unknown>) {
    const socket = socketRef.current
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(event))
  }

  function playAudio(base64Audio: string) {
    const context = playbackContextRef.current
    if (!context) return
    const binary = atob(base64Audio)
    const sampleCount = Math.floor(binary.length / 2)
    if (sampleCount === 0) return
    const buffer = context.createBuffer(1, sampleCount, OUTPUT_SAMPLE_RATE)
    const channel = buffer.getChannelData(0)
    for (let index = 0; index < sampleCount; index += 1) {
      const low = binary.charCodeAt(index * 2)
      const high = binary.charCodeAt(index * 2 + 1)
      const value = (high << 8) | low
      channel[index] = (value >= 0x8000 ? value - 0x10000 : value) / 0x8000
    }
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    const startAt = Math.max(context.currentTime, nextPlaybackTimeRef.current)
    playingRef.current.add(source)
    source.onended = () => {
      playingRef.current.delete(source)
      if (playingRef.current.size === 0) setState("listening")
    }
    source.start(startAt)
    nextPlaybackTimeRef.current = startAt + buffer.duration
    setState("speaking")
  }

  function handleToolCall(id: string, message: string) {
    const existingDraft = draftRef.current.trim()
    const separator = existingDraft ? "\n\n" : ""
    const availableLength = MAX_DRAFT_LENGTH - existingDraft.length - separator.length
    let drafted = false
    if (availableLength <= 0) {
      setError("Amber's chat draft is full. Shorten it before asking Opal to add another request.")
    } else {
      onDraftChange(`${existingDraft}${separator}${message.trim().slice(0, availableLength)}`)
      addLine("opal", "I added a request to Amber's chat box. Review it there, then press Send when you're ready.")
      drafted = true
    }
    send({ type: "tool_result", id, drafted })
  }

  /** Applies one relay event and returns its type. */
  function handleLiveEvent(raw: string): string | null {
    let event: unknown
    try {
      event = JSON.parse(raw)
    } catch (parseError) {
      console.error("Could not parse Opal voice event", parseError)
      return null
    }
    if (typeof event !== "object" || event === null) return null

    const type = stringField(event, "type")
    switch (type) {
      case "input_transcript":
        assistantLineIdRef.current = null
        appendTranscript("you", stringField(event, "text") ?? "")
        setState("thinking")
        break
      case "output_transcript":
        userLineIdRef.current = null
        appendTranscript("opal", stringField(event, "text") ?? "")
        break
      case "audio": {
        const data = stringField(event, "data")
        if (data) playAudio(data)
        break
      }
      case "interrupted":
        // The user talked over Opal: drop the rest of the reply that is already queued.
        stopPlayback()
        assistantLineIdRef.current = null
        setState("listening")
        break
      case "turn_complete":
        userLineIdRef.current = null
        assistantLineIdRef.current = null
        if (playingRef.current.size === 0) setState("listening")
        break
      case "tool_call": {
        const id = stringField(event, "id")
        const message = stringField(event, "message")
        if (id && message) handleToolCall(id, message)
        break
      }
      case "error":
        console.error("Opal voice service reported an error", event)
        setError(stringField(event, "message") ?? "The voice service reported an error.")
        break
    }
    return type
  }

  async function startCapture(captureContext: AudioContext, stream: MediaStream, socket: WebSocket) {
    const source = captureContext.createMediaStreamSource(stream)
    const mute = captureContext.createGain()
    mute.gain.value = 0
    const sendSamples = (samples: Float32Array) => {
      if (mutedRef.current || socket.readyState !== WebSocket.OPEN) return
      socket.send(JSON.stringify({ type: "audio", data: encodePcm16(samples, captureContext.sampleRate) }))
    }

    let processor: AudioNode
    try {
      await captureContext.audioWorklet.addModule("/opal-pcm-capture.js")
      const worklet = new AudioWorkletNode(captureContext, "opal-pcm-capture")
      worklet.port.onmessage = (message: MessageEvent<Float32Array>) => sendSamples(message.data)
      processor = worklet
    } catch (workletError) {
      // Older browsers, or a CSP that blocks worklet modules: fall back to the deprecated processor.
      console.warn("Opal is using ScriptProcessor capture", workletError)
      const scriptProcessor = captureContext.createScriptProcessor(4096, 1, 1)
      scriptProcessor.onaudioprocess = (audioEvent) => sendSamples(audioEvent.inputBuffer.getChannelData(0))
      processor = scriptProcessor
    }
    source.connect(processor)
    processor.connect(mute)
    mute.connect(captureContext.destination)
    captureNodesRef.current = [source, processor, mute]
  }

  async function startSession() {
    if (!config?.enabled || connecting || connected) return
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Microphone access is unavailable in this browser.")
      return
    }

    setConnecting(true)
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      streamRef.current = stream
      const captureContext = new AudioContext()
      const playbackContext = new AudioContext({ sampleRate: OUTPUT_SAMPLE_RATE })
      captureContextRef.current = captureContext
      playbackContextRef.current = playbackContext
      await Promise.all([captureContext.resume(), playbackContext.resume()])

      const socket = new WebSocket(liveSocketUrl())
      socketRef.current = socket
      const ready = new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error("Timed out connecting to voice.")), 15000)
        socket.onmessage = (message) => {
          if (typeof message.data === "string" && handleLiveEvent(message.data) === "ready") {
            window.clearTimeout(timeout)
            resolve()
          }
        }
        socket.addEventListener("close", (event) => {
          window.clearTimeout(timeout)
          reject(new Error(event.reason || "The voice service closed the connection."))
        }, { once: true })
      })
      ready.catch(() => undefined) // awaited below; this only stops an early close being reported as unhandled
      socket.onclose = (event) => {
        if (socketRef.current !== socket) return
        socketRef.current = null
        resetSession()
        if (event.code !== 1000) setError(event.reason || "The voice connection closed. Reconnect to continue.")
        else if (event.reason) setError(event.reason)
      }
      await new Promise<void>((resolve, reject) => {
        socket.addEventListener("open", () => resolve(), { once: true })
        socket.addEventListener("error", () => reject(new Error("Could not connect to the voice service.")), {
          once: true,
        })
      })

      sentContextRef.current = contextRef.current
      socket.send(JSON.stringify({ type: "start", context: contextRef.current }))
      await ready
      await startCapture(captureContext, stream, socket)
      setConnected(true)
      setConnecting(false)
      setState("listening")
    } catch (startError) {
      console.error("Failed to start Opal voice session", startError)
      stopSession()
      setError(errorMessage(startError))
    }
  }

  function toggleMute() {
    mutedRef.current = !mutedRef.current
    setMuted(mutedRef.current)
  }

  // Keep Opal in step with the chat: new replies, tasks and approvals are sent as context updates.
  useEffect(() => {
    if (!connected) return
    const timeout = window.setTimeout(() => {
      if (context === sentContextRef.current) return
      sentContextRef.current = context
      send({ type: "context", context })
    }, 700)
    return () => window.clearTimeout(timeout)
  }, [connected, context])

  const canStart = config?.enabled === true && !connecting && !connected

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card/70">
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <div className="min-w-0">
          <h2 className="text-sm font-medium">Opal</h2>
          <p className="truncate text-[11px] text-muted-foreground">
            {connected ? "Talking through this chat" : "Your voice companion for this chat"}
          </p>
        </div>
        <span className={cn("size-2 shrink-0 rounded-full", connected ? "bg-success" : "bg-muted-foreground/40")} />
      </div>

      <div className="flex min-h-0 flex-1 flex-col items-center overflow-hidden p-3">
        <Persona
          state={state}
          variant="opal"
          className="size-28 max-h-32 max-w-full shrink-0"
          onLoadError={(loadError) => {
            console.error("Failed to load Opal persona animation", loadError)
            setError("The Opal animation could not be loaded.")
          }}
        />
        <div aria-live="polite" className="mt-1 w-full min-h-0 flex-1 space-y-2 overflow-y-auto text-xs">
          {lines.map((line) => (
            <div
              className={cn(
                "rounded-lg px-2.5 py-2 leading-relaxed",
                line.role === "opal" ? "bg-muted/70" : "bg-primary/10",
              )}
              key={line.id}
            >
              <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {line.role === "opal" ? "Opal" : "You"}
                </span>
                {line.text}
            </div>
          ))}
          {lines.length === 0 && (
            <p className="px-2 py-3 text-center leading-relaxed text-muted-foreground">
              {connected
                ? "Go ahead — ask about the conversation or talk through what you need."
                : "Start a voice session to discuss recent replies and prepare your next request."}
            </p>
          )}
          {!config && !configError && (
            <p role="status" className="text-center text-muted-foreground">Checking voice availability…</p>
          )}
          {configError && (
            <p role="alert" className="text-center text-destructive">Voice availability could not be checked.</p>
          )}
          {config && !config.enabled && (
            <p className="text-center text-muted-foreground">
              Live voice is not configured on this Amber server yet.
            </p>
          )}
          {config?.model && (
            <p className="text-center text-[10px] text-muted-foreground">Live model · {config.model}</p>
          )}
          {error && <p role="alert" className="text-center text-destructive">{error}</p>}
          {draft && (
            <p className="rounded-md border border-primary/30 bg-primary/5 px-2 py-1.5 text-[11px]">
              Draft is waiting in Amber&apos;s composer. Review it and press Send when ready.
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center justify-center gap-2 border-t p-3">
        {connected ? (
          <>
            <span className="mr-auto flex items-center gap-1.5 text-[11px] text-muted-foreground">
              {muted ? <MicOff className="size-3" /> : state === "speaking" ? <Volume2 className="size-3" /> : <Mic className="size-3" />}
              {muted ? "Muted" : state === "speaking" ? "Speaking" : "Listening"}
            </span>
            <Button aria-pressed={muted} onClick={toggleMute} size="sm" variant="ghost">
              {muted ? "Unmute" : "Mute"}
            </Button>
            <Button onClick={stopSession} size="sm" variant="outline">
              <PhoneOff className="mr-1 size-3.5" />
              Stop
            </Button>
          </>
        ) : (
          <Button className="w-full" disabled={!canStart} onClick={() => void startSession()} size="sm">
            {connecting ? (
              <LoaderCircle className="mr-1 size-3.5 animate-spin" />
            ) : (
              <Mic className="mr-1 size-3.5" />
            )}
            {connecting ? "Connecting…" : "Talk to Opal"}
          </Button>
        )}
      </div>
    </section>
  )
}
