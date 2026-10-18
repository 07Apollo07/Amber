"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Check, ChevronDown, Cpu, FolderOpen, MessageSquare, MoreHorizontal, Pencil, Plus, Trash2, X } from "lucide-react"

import { AmberMark } from "@/components/app/amber-logo"
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation"
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message"
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputButton,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input"
import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector"
import { Shimmer } from "@/components/ai-elements/shimmer"
import {
  Queue,
  QueueItem,
  QueueItemContent,
  QueueItemIndicator,
  QueueList,
  QueueSection,
  QueueSectionContent,
  QueueSectionLabel,
  QueueSectionTrigger,
} from "@/components/ai-elements/queue"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { apiDelete, apiPost, apiPut } from "@/lib/api"
import { demoAction } from "@/lib/demo"
import type { Conversation as ConversationRecord } from "@/lib/types"
import { cn } from "@/lib/utils"

import {
  GenerativeVisualCard,
  isGenerativeVisual,
  type GenerativeVisual,
} from "./generative-visual"
import { LiveSidekick } from "./live-sidekick"
import { ToolElement } from "./tool-element"

type TextEntry = {
  id: string
  kind: "text"
  role: "user" | "assistant"
  text: string
}

type ToolEntry = {
  id: string
  kind: "tool"
  callId: string
  name: string
  args: string
  result?: string
  status: "running" | "success" | "failed"
}

type VisualEntry = {
  id: string
  kind: "visual"
  visual: GenerativeVisual
}

type TimelineEntry = TextEntry | ToolEntry | VisualEntry
type AgentModelsResponse = {
  enabled: boolean
  default_model: string
  models: string[]
}
type AgentCollection = { id: string; name: string }

function isAgentModelsResponse(value: unknown): value is AgentModelsResponse {
  return (
    isRecord(value) &&
    typeof value.enabled === "boolean" &&
    typeof value.default_model === "string" &&
    Array.isArray(value.models) &&
    value.models.every((model) => typeof model === "string")
  )
}

function isAgentCollectionsResponse(value: unknown): value is { collections: AgentCollection[] } {
  return (
    isRecord(value) &&
    Array.isArray(value.collections) &&
    value.collections.every(
      (collection) =>
        isRecord(collection) && typeof collection.id === "string" && typeof collection.name === "string",
    )
  )
}

const generativeUiTools = new Set([
  "render_chart",
  "render_table",
  "render_metric_cards",
  "render_comparison",
  "render_timeline",
  "render_source_cards",
])
type TaskStatus = "pending" | "in_progress" | "completed" | "failed"
type AgentTask = { id: string; title: string; status: TaskStatus }
function readAgentTasks(value: unknown): AgentTask[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (task): task is AgentTask =>
      isRecord(task) &&
      typeof task.id === "string" &&
      typeof task.title === "string" &&
      (task.status === "pending" ||
        task.status === "in_progress" ||
        task.status === "completed" ||
        task.status === "failed"),
  )
}

const taskIdsByTool: Record<string, string> = {
  vector_search: "find-files",
  get_file: "read-source",
  create_google_doc: "edit-document",
  edit_google_doc: "edit-document",
  create_google_sheet: "edit-document",
  edit_google_sheet: "edit-document",
}
type WorkspaceFile = {
  documentId: string
  title: string
  content: string
  driveUrl: string
  mimeType: string
  values?: (string | number | boolean | null)[][]
}
type WorkspaceApproval = {
  operation_id: string
  kind: string
  title: string
  url?: string
  before?: string | null
  after: string
}

type AgentToolCall = {
  id?: string
  name?: string
  args?: unknown
}

type AgentMessage = {
  id?: string
  type?: string
  role?: string
  content?: unknown
  tool_calls?: AgentToolCall[]
  tool_call_id?: string
  name?: string
  status?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function getMessageText(content: unknown): string {
  if (typeof content === "string") return content
  if (!Array.isArray(content)) return ""

  return content
    .map((part) => {
      if (typeof part === "string") return part
      if (isRecord(part) && typeof part.text === "string") return part.text
      return ""
    })
    .join("")
}

function formatToolArgs(args: unknown): string {
  if (typeof args === "string") return args
  if (args === undefined || args === null) return "{}"
  return JSON.stringify(args, null, 2)
}

function parseWorkspaceFileResult(result: string): {
  file: WorkspaceFile
  summary: string
} | null {
  try {
    const payload = JSON.parse(result) as {
      document_id?: string
      title?: string
      content?: string
      drive_url?: string
      mime_type?: string
      values?: unknown[][]
    }
    if (
      !payload.document_id ||
      (typeof payload.content !== "string" && !Array.isArray(payload.values))
    ) {
      return null
    }
    return {
      file: {
        documentId: payload.document_id,
        title: payload.title || "Workspace file",
        content: typeof payload.content === "string"
          ? payload.content
          : (payload.values || []).map((row) => row.map(String).join("\t")).join("\n"),
        driveUrl: payload.drive_url || "",
        mimeType: payload.mime_type || "",
        values: Array.isArray(payload.values)
          ? payload.values as (string | number | boolean | null)[][]
          : undefined,
      },
      summary: `Workspace file: ${payload.title || "file"}`,
    }
  } catch {
    return null
  }
}

function getMessagesFromUpdate(data: unknown): AgentMessage[] {
  if (!isRecord(data)) return []
  if (Array.isArray(data.messages)) return data.messages as AgentMessage[]

  return Object.values(data).flatMap((nodeUpdate) => {
    if (!isRecord(nodeUpdate) || !Array.isArray(nodeUpdate.messages)) return []
    return nodeUpdate.messages as AgentMessage[]
  })
}

function isAssistantMessage(message: AgentMessage): boolean {
  const role = message.type || message.role || ""
  return role === "ai" || role === "assistant" || role === "AIMessage" || role === "AIMessageChunk"
}

function isToolMessage(message: AgentMessage): boolean {
  const role = message.type || message.role || ""
  return role === "tool" || role === "ToolMessage" || Boolean(message.tool_call_id)
}

function makeHistory(messages: AgentMessage[], savedVisuals: unknown): TimelineEntry[] {
  const entries: TimelineEntry[] = []
  const visualsById = new Map<string, GenerativeVisual>()
  if (isRecord(savedVisuals)) {
    for (const candidate of Object.values(savedVisuals)) {
      if (isGenerativeVisual(candidate)) visualsById.set(candidate.id, candidate)
    }
  }
  const renderedVisualIds = new Set<string>()

  for (const [messageIndex, message] of messages.entries()) {
    const role = message.type || message.role || ""
    const text = getMessageText(message.content)

    if (role === "human" || role === "user") {
      entries.push({
        id: message.id || `user-${messageIndex}`,
        kind: "text",
        role: "user",
        text,
      })
      continue
    }

    if (isAssistantMessage(message)) {
      if (text) {
        entries.push({
          id: message.id || `assistant-${messageIndex}`,
          kind: "text",
          role: "assistant",
          text,
        })
      }

      for (const [callIndex, call] of (message.tool_calls || []).entries()) {
        const callId = call.id || `${message.id || messageIndex}-${callIndex}`
        if (call.name && generativeUiTools.has(call.name)) {
          const visual = visualsById.get(callId)
          if (visual) {
            entries.push({ id: `visual-${visual.id}`, kind: "visual", visual })
            renderedVisualIds.add(visual.id)
          }
          continue
        }
        entries.push({
          id: `tool-${callId}`,
          kind: "tool",
          callId,
          name: call.name || "Tool",
          args: formatToolArgs(call.args),
          status: "running",
        })
      }
      continue
    }

    if (isToolMessage(message)) {
      const callId = message.tool_call_id || `tool-result-${messageIndex}`
      if (message.name && generativeUiTools.has(message.name)) continue
      const existing = entries.find(
        (entry): entry is ToolEntry => entry.kind === "tool" && entry.callId === callId,
      )
      const result = text || formatToolArgs(message.content)
      const workspaceFile = parseWorkspaceFileResult(result)
      if (existing) {
        existing.result = workspaceFile?.summary || result
        existing.status = message.status === "error" ? "failed" : "success"
      } else {
        entries.push({
          id: `tool-${callId}`,
          kind: "tool",
          callId,
          name: message.name || "Tool",
          args: "{}",
          result: workspaceFile?.summary || result,
          status: message.status === "error" ? "failed" : "success",
        })
      }
    }
  }

  for (const visual of visualsById.values()) {
    if (!renderedVisualIds.has(visual.id)) {
      entries.push({ id: `visual-${visual.id}`, kind: "visual", visual })
    }
  }

  return entries
}

export function ChatLayout() {
  const [conversations, setConversations] = useState<ConversationRecord[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [entries, setEntries] = useState<TimelineEntry[]>([])
  const [tasks, setTasks] = useState<AgentTask[]>([])
  const [workspaceFile, setWorkspaceFile] = useState<WorkspaceFile | null>(null)
  const [approval, setApproval] = useState<WorkspaceApproval | null>(null)
  const [draft, setDraft] = useState("")
  const [loading, setLoading] = useState(false)
  const [modelOptions, setModelOptions] = useState<AgentModelsResponse | null>(null)
  const [selectedModel, setSelectedModel] = useState<string | null>(null)
  const [modelPickerOpen, setModelPickerOpen] = useState(false)
  const [modelLoadError, setModelLoadError] = useState(false)
  const [collections, setCollections] = useState<AgentCollection[]>([])
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null)
  const [collectionLoadError, setCollectionLoadError] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState("")
  const [savingConversationId, setSavingConversationId] = useState<string | null>(null)
  const [sidekickOpen, setSidekickOpen] = useState(false)
  const skipNextLoadRef = useRef<string | null>(null)
  const taskPlanActiveRef = useRef(false)
  // Bumped only when the user switches chats, so a new chat getting its thread id doesn't end the voice session.
  const [sidekickSession, setSidekickSession] = useState(0)
  const sidekickContext = useMemo(() => {
    const recentMessages = entries
      .flatMap((entry) => {
        if (entry.kind === "text") {
          const text = entry.text.length > 1500 ? `${entry.text.slice(0, 1500)}…` : entry.text
          return [`${entry.role === "user" ? "User" : "Amber"}: ${text}`]
        }
        if (entry.kind === "tool") return [`[Amber used ${entry.name}: ${entry.status}]`]
        return []
      })
      .slice(-16)
      .join("\n")
    const taskSummary = tasks.map((task) => `${task.title} (${task.status})`).join("\n")
    const collection = collections.find((item) => item.id === selectedCollectionId)
    return [
      `Active conversation: ${activeId || "new conversation"}`,
      `Searching: ${collection ? `the "${collection.name}" collection` : "all of the user's documents"}`,
      loading && "Amber is still working on its latest reply.",
      recentMessages && `Recent conversation:\n${recentMessages}`,
      taskSummary && `Current tasks:\n${taskSummary}`,
      approval && `Approval awaiting the user's decision: ${approval.title}`,
    ]
      .filter(Boolean)
      .join("\n\n")
      .slice(-8000)
  }, [activeId, approval, collections, entries, loading, selectedCollectionId, tasks])

  async function fetchConversations(): Promise<ConversationRecord[]> {
    const response = await fetch("/api/agent/conversations")
    if (!response.ok) {
      throw new Error(`Failed to load conversations (${response.status})`)
    }
    return response.json()
  }

  useEffect(() => {
    fetchConversations()
      .then(setConversations)
      .catch((error: unknown) => console.error("Failed to load conversations", error))
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    async function fetchModels() {
      try {
        const response = await fetch("/api/agent/models", {
          cache: "no-store",
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(`Failed to load models (${response.status})`)
        const data: unknown = await response.json()
        if (!isAgentModelsResponse(data)) throw new Error("The model list response is invalid")
        setModelOptions(data)
      } catch (error) {
        if (!controller.signal.aborted) {
          console.error("Failed to load available models", error)
          setModelLoadError(true)
        }
      }
    }

    void fetchModels()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    async function fetchCollections() {
      try {
        const response = await fetch("/api/collections", {
          cache: "no-store",
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(`Failed to load collections (${response.status})`)
        const data: unknown = await response.json()
        if (!isAgentCollectionsResponse(data)) throw new Error("The collection list response is invalid")
        setCollections(data.collections)
      } catch (error) {
        if (!controller.signal.aborted) {
          console.error("Failed to load available collections", error)
          setCollectionLoadError(true)
        }
      }
    }

    void fetchCollections()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!activeId) return
    if (skipNextLoadRef.current === activeId) {
      skipNextLoadRef.current = null
      return
    }

    const controller = new AbortController()
    async function loadThread() {
      try {
        const response = await fetch(`/api/agent/conversations/${activeId}`, {
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error(`Failed to load conversation (${response.status})`)
        }
        const data: {
          messages?: AgentMessage[]
          tasks?: unknown
          visuals?: unknown
          error?: string
          pending_approval?: WorkspaceApproval | null
        } = await response.json()
        if (data.error) throw new Error(data.error)
        const restoredTasks = readAgentTasks(data.tasks)
        setEntries(makeHistory(data.messages || [], data.visuals))
        setTasks(restoredTasks)
        taskPlanActiveRef.current = restoredTasks.length > 0
        setApproval(data.pending_approval || null)
        const lastWorkspaceResult = [...(data.messages || [])].reverse().find((message) =>
          isToolMessage(message) &&
          ["get_file", "create_google_doc", "edit_google_doc", "create_google_sheet", "edit_google_sheet"]
            .includes(message.name || ""),
        )
        const fileData = lastWorkspaceResult
          ? parseWorkspaceFileResult(getMessageText(lastWorkspaceResult.content))
          : null
        setWorkspaceFile(fileData?.file || null)
      } catch (error) {
        if (!controller.signal.aborted) {
          console.error("Failed to load conversation", error)
          demoAction(
            "Failed to load conversation",
            error instanceof Error ? error.message : String(error),
          )
        }
      }
    }

    void loadThread()
    return () => controller.abort()
  }, [activeId])

  function addOrUpdateTool(call: AgentToolCall, index: number, messageId?: string) {
    if (call.name && generativeUiTools.has(call.name)) return
    const callId = call.id || `${messageId || "tool"}-${index}`
    const id = `tool-${callId}`
    setEntries((current) => {
      const existingIndex = current.findIndex(
        (entry) => entry.kind === "tool" && entry.callId === callId,
      )
      const toolEntry: ToolEntry = {
        id,
        kind: "tool",
        callId,
        name: call.name || "Tool",
        args: formatToolArgs(call.args),
        status: "running",
      }

      if (existingIndex < 0) return [...current, toolEntry]
      return current.map((entry, entryIndex) =>
        entryIndex === existingIndex && entry.kind === "tool"
          ? { ...entry, ...toolEntry, result: entry.result, status: entry.status }
          : entry,
      )
    })
  }

  function addOrUpdateToolResult(message: AgentMessage) {
    const callId = message.tool_call_id
    if (!callId) return
    if (message.name && generativeUiTools.has(message.name)) return
    if (message.status === "error" && !taskPlanActiveRef.current) {
      const taskId = message.name ? taskIdsByTool[message.name] : undefined
      if (taskId) {
        setTasks((current) => {
          const existing = current.find((task) => task.id === taskId)
          const failedTask: AgentTask = {
            id: taskId,
            title: existing?.title || "Workspace operation",
            status: "failed",
          }
          return existing
            ? current.map((task) => (task.id === taskId ? failedTask : task))
            : [...current, failedTask]
        })
      }
    }
    let result = getMessageText(message.content) || formatToolArgs(message.content)
    const filePayload = parseWorkspaceFileResult(result)
    if (filePayload) {
      setWorkspaceFile(filePayload.file)
      result = `${message.name === "get_file" ? "Read full source" : "Updated workspace file"}: ${filePayload.file.title}`
    }
    setEntries((current) => {
      const existingIndex = current.findIndex(
        (entry) => entry.kind === "tool" && entry.callId === callId,
      )
      if (existingIndex < 0) {
        return [
          ...current,
          {
            id: `tool-${callId}`,
            kind: "tool",
            callId,
            name: message.name || "Tool",
            args: "{}",
            result,
            status: message.status === "error" ? "failed" : "success",
          },
        ]
      }
      return current.map((entry, index) =>
        index === existingIndex && entry.kind === "tool"
          ? {
              ...entry,
              result,
              status: message.status === "error" ? "failed" : "success",
            }
          : entry,
      )
    })
  }

  function failActiveTasks() {
    setTasks((current) =>
      current.map((task) =>
        task.status === "in_progress" || task.status === "pending"
          ? { ...task, status: "failed" }
          : task,
      ),
    )
  }

  async function runAgentStream(
    response: Response,
    startingThreadId: string | null,
    shouldGenerateTitle: boolean,
  ) {
    if (!response.body) throw new Error("The chat stream did not include a response body.")
    let threadId = startingThreadId
    const textEntryIds = new Map<string, string>()
    const fallbackTextId = crypto.randomUUID()

    function appendAssistantText(message: AgentMessage, content: string) {
      const messageId = message.id || "assistant"
      const entryId = textEntryIds.get(messageId) || fallbackTextId
      textEntryIds.set(messageId, entryId)
      setEntries((current) => {
        const existing = current.find(
          (entry): entry is TextEntry => entry.kind === "text" && entry.id === entryId,
        )
        if (existing) {
          return current.map((entry) =>
            entry.kind === "text" && entry.id === entryId
              ? { ...entry, text: entry.text + content }
              : entry,
          )
        }
        return [...current, { id: entryId, kind: "text", role: "assistant", text: content }]
      })
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    let eventName = ""
    let streamEnded = false
    while (!streamEnded) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n")
      buffer = lines.pop() || ""
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventName = line.slice(7).trim()
          continue
        }
        if (!line.startsWith("data: ")) continue
        const rawData = line.slice(6).trim()
        if (rawData === "[DONE]") {
          streamEnded = true
          break
        }
        let data: unknown
        try {
          data = JSON.parse(rawData)
        } catch (error) {
          throw new Error(
            `Could not read ${eventName || "chat"} stream data: ${
              error instanceof Error ? error.message : String(error)
            }`,
          )
        }
        if (eventName === "metadata" && isRecord(data) && typeof data.thread_id === "string") {
          threadId = data.thread_id
          skipNextLoadRef.current = threadId === activeId ? null : threadId
          setActiveId(threadId)
          continue
        }
        if (eventName === "error") {
          throw new Error(isRecord(data) && typeof data.error === "string" ? data.error : "The agent stream failed.")
        }
        if (eventName === "approval" && isRecord(data) && typeof data.operation_id === "string") {
          setApproval({
            operation_id: data.operation_id,
            kind: typeof data.kind === "string" ? data.kind : "document_change",
            title: typeof data.title === "string" ? data.title : "Proposed document change",
            url: typeof data.url === "string" ? data.url : undefined,
            before: typeof data.before === "string" ? data.before : null,
            after: typeof data.after === "string" ? data.after : "",
          })
          continue
        }
        if (eventName.startsWith("custom") && isRecord(data) && data.type === "task_update") {
          if (
            typeof data.id === "string" &&
            typeof data.title === "string" &&
            (data.status === "pending" ||
              data.status === "in_progress" ||
              data.status === "completed" ||
              data.status === "failed")
          ) {
            const task: AgentTask = { id: data.id, title: data.title, status: data.status }
            setTasks((current) => {
              const exists = current.some((item) => item.id === task.id)
              if (taskPlanActiveRef.current && !exists) return current
              return exists
                ? current.map((item) => (item.id === task.id ? task : item))
                : [...current, task]
            })
          }
          continue
        }
        if (eventName.startsWith("custom") && isRecord(data) && data.type === "task_plan") {
          const updatedTasks = readAgentTasks(data.tasks)
          taskPlanActiveRef.current = updatedTasks.length > 0
          setTasks(updatedTasks)
          continue
        }
        if (
          eventName.startsWith("custom") &&
          isRecord(data) &&
          data.type === "generative_ui" &&
          isGenerativeVisual(data.visual)
        ) {
          const visual = data.visual
          setEntries((current) => {
            const entry: VisualEntry = { id: `visual-${visual.id}`, kind: "visual", visual }
            const existingIndex = current.findIndex(
              (item) => item.kind === "visual" && item.visual.id === visual.id,
            )
            if (existingIndex < 0) return [...current, entry]
            return current.map((item, index) => (index === existingIndex ? entry : item))
          })
          continue
        }
        if (eventName.startsWith("messages") && Array.isArray(data) && isRecord(data[0])) {
          const message = data[0] as AgentMessage
          if (isAssistantMessage(message)) {
            const content = getMessageText(message.content)
            if (content) appendAssistantText(message, content)
            for (const [index, call] of (message.tool_calls || []).entries()) {
              addOrUpdateTool(call, index, message.id)
            }
          } else if (isToolMessage(message)) {
            addOrUpdateToolResult(message)
          }
          continue
        }
        if (eventName.startsWith("updates")) {
          for (const message of getMessagesFromUpdate(data)) {
            if (isAssistantMessage(message)) {
              for (const [index, call] of (message.tool_calls || []).entries()) {
                addOrUpdateTool(call, index, message.id)
              }
            } else if (isToolMessage(message)) {
              addOrUpdateToolResult(message)
            }
          }
        }
      }
    }
    await reader.cancel()

    if (shouldGenerateTitle && threadId) {
      try {
        const titleResponse = await apiPost(`/api/agent/conversations/${threadId}/generate-title`)
        const titledConversation: { title: string } = await titleResponse.json()
        setConversations((current) =>
          current.map((conversation) =>
            conversation.id === threadId ? { ...conversation, title: titledConversation.title } : conversation,
          ),
        )
      } catch (error) {
        console.error("Failed to generate conversation title", error)
      }
    }
    fetchConversations()
      .then(setConversations)
      .catch((error: unknown) => console.error("Failed to refresh conversations", error))
  }

  async function respondToApproval(decision: "approve" | "reject") {
    if (!activeId || !approval || loading) return
    setLoading(true)
    setApproval(null)
    try {
      const response = await apiPost("/api/agent/v2/stream", {
        thread_id: activeId,
        decision,
        operation_id: approval.operation_id,
        model: selectedModel ?? undefined,
      })
      await runAgentStream(response, activeId, false)
    } catch (error) {
      failActiveTasks()
      setApproval(approval)
      demoAction(
        "Failed to process document approval",
        error instanceof Error ? error.message : String(error),
      )
    } finally {
      setLoading(false)
    }
  }

  async function send(text: string) {
    const trimmedText = text.trim()
    if (!trimmedText || loading) return

    const shouldGenerateTitle = activeId === null
    setEntries((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        kind: "text",
        role: "user",
        text: trimmedText,
      },
    ])
    setDraft("")
    setLoading(true)
    taskPlanActiveRef.current = false
    setTasks([])
    setWorkspaceFile(null)
    setApproval(null)

    try {
      const response = await apiPost("/api/agent/v2/stream", {
        message: trimmedText,
        thread_id: activeId,
        model: selectedModel ?? undefined,
        collection_id: selectedCollectionId ?? undefined,
      })
      await runAgentStream(response, activeId, shouldGenerateTitle)
    } catch (error) {
      failActiveTasks()
      demoAction(
        "Failed to send message",
        error instanceof Error ? error.message : String(error),
      )
    } finally {
      setLoading(false)
    }
  }

  function newChat() {
    skipNextLoadRef.current = null
    setSidekickSession((value) => value + 1)
    setActiveId(null)
    setEntries([])
    taskPlanActiveRef.current = false
    setTasks([])
    setWorkspaceFile(null)
    setApproval(null)
  }

  function selectConversation(id: string) {
    if (id === activeId) return
    skipNextLoadRef.current = null
    setSidekickSession((value) => value + 1)
    setEntries([])
    taskPlanActiveRef.current = false
    setTasks([])
    setWorkspaceFile(null)
    setApproval(null)
    setActiveId(id)
  }

  function beginRename(conversation: ConversationRecord) {
    setEditingId(conversation.id)
    setEditingTitle(conversation.title)
  }

  async function saveRename(conversationId: string) {
    const title = editingTitle.trim()
    if (!title || savingConversationId) return

    setSavingConversationId(conversationId)
    try {
      const response = await apiPut(`/api/agent/conversations/${conversationId}`, { name: title })
      const updated: { title: string } = await response.json()
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === conversationId
            ? { ...conversation, title: updated.title }
            : conversation,
        ),
      )
      setEditingId(null)
      setEditingTitle("")
    } catch (error) {
      demoAction(
        "Failed to rename conversation",
        error instanceof Error ? error.message : String(error),
      )
    } finally {
      setSavingConversationId(null)
    }
  }

  async function deleteConversation(conversation: ConversationRecord) {
    if (!window.confirm(`Delete “${conversation.title}”? This cannot be undone.`)) return

    setSavingConversationId(conversation.id)
    try {
      await apiDelete(`/api/agent/conversations/${conversation.id}`)
      setConversations((current) =>
        current.filter((item) => item.id !== conversation.id),
      )
      if (activeId === conversation.id) newChat()
    } catch (error) {
      demoAction(
        "Failed to delete conversation",
        error instanceof Error ? error.message : String(error),
      )
    } finally {
      setSavingConversationId(null)
    }
  }

  return (
    <div className="grid h-[calc(100dvh-5.5rem)] min-h-[520px] w-full grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,4fr)] xl:grid-cols-[minmax(0,1fr)_minmax(0,3fr)_minmax(260px,1fr)]">
      <aside className="hidden min-w-0 flex-col overflow-hidden rounded-2xl border bg-card/70 p-3 lg:flex">
        <div className="mb-2 flex items-center justify-between border-b px-1 pb-3">
          <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <MessageSquare className="size-3.5" />
            Conversations
          </span>
          <Button variant="ghost" size="icon-xs" onClick={newChat} aria-label="New chat">
            <Plus className="size-3.5" />
          </Button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto pr-1">
          {conversations.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">
              Your conversations will appear here.
            </p>
          ) : (
            conversations.map((conversation) => (
              <div
                key={conversation.id}
                className="group flex items-start gap-1 rounded-lg pr-1 transition-colors hover:bg-muted/80"
              >
                <button
                  type="button"
                  onClick={() => selectConversation(conversation.id)}
                  className={cn(
                    "min-w-0 flex-1 px-2.5 py-2 text-left text-xs",
                    activeId === conversation.id && "font-medium text-primary",
                  )}
                >
                  <span className="block truncate">{conversation.title}</span>
                  <span className="mt-1 block text-[10px] text-muted-foreground">
                    {conversation.updatedAt}
                  </span>
                </button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      className="mt-1 shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                      aria-label={`Actions for ${conversation.title}`}
                      disabled={savingConversationId === conversation.id}
                    >
                      <MoreHorizontal className="size-3.5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-40">
                    <DropdownMenuItem onSelect={() => beginRename(conversation)}>
                      <Pencil />
                      Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      variant="destructive"
                      onSelect={() => void deleteConversation(conversation)}
                    >
                      <Trash2 />
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ))
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-card/40">
        <header className="flex items-center justify-between gap-3 border-b bg-muted/20 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10">
              <AmberMark className="size-5" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold">Amber Assistant</h1>
              <p className="truncate text-xs text-muted-foreground">
                Chat with your documents and tools
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={newChat} className="shrink-0">
            <Plus className="size-4" />
            New chat
          </Button>
        </header>

        {conversations.length > 0 && (
          <nav
            aria-label="Recent conversations"
            className="flex gap-2 overflow-x-auto border-b px-3 py-2 lg:hidden"
          >
            {conversations.map((conversation) => (
              <div
                key={conversation.id}
              >
                <div
                  className={cn(
                    "flex max-w-56 shrink-0 items-center rounded-full border text-xs text-muted-foreground transition-colors hover:bg-muted",
                    activeId === conversation.id && "border-primary/50 bg-primary/10 text-foreground",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => selectConversation(conversation.id)}
                    className="min-w-0 truncate py-1.5 pl-3 pr-1 text-left"
                  >
                    {conversation.title}
                  </button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        className="mr-1 size-6 shrink-0"
                        aria-label={`Actions for ${conversation.title}`}
                      >
                        <MoreHorizontal className="size-3.5" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-40">
                      <DropdownMenuItem onSelect={() => beginRename(conversation)}>
                        <Pencil />
                        Rename
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        variant="destructive"
                        onSelect={() => void deleteConversation(conversation)}
                      >
                        <Trash2 />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>
            ))}
          </nav>
        )}

        <Conversation className="min-h-0 flex-1">
          <ConversationContent className="mx-auto w-full max-w-4xl flex-1 gap-6 px-4 py-6 sm:px-6 sm:py-8">
            {entries.length === 0 ? (
              <ConversationEmptyState
                className="min-h-[min(55vh,460px)]"
                icon={
                  <div className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-primary/10">
                    <AmberMark className="size-7" />
                  </div>
                }
                title="What can I help you with?"
                description="Ask a question and follow the assistant's tool activity and results as it works."
              />
            ) : (
              entries.map((entry) => (
                <Message
                  from={entry.kind === "text" ? entry.role : "assistant"}
                  key={entry.id}
                  className="max-w-full"
                >
                  {entry.kind === "visual" ? (
                    <div className="w-full">
                      <GenerativeVisualCard visual={entry.visual} />
                    </div>
                  ) : entry.kind === "text" && entry.role === "user" ? (
                    <MessageContent className="max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary/12 px-4 py-3 text-[15px] leading-6">
                      {entry.text}
                    </MessageContent>
                  ) : entry.kind === "text" ? (
                    <div className="flex w-full gap-3">
                      <AmberMark className="mt-1 size-6 shrink-0" />
                      <MessageContent className="min-w-0 flex-1 overflow-visible">
                        <MessageResponse isAnimating={loading}>
                          {entry.text}
                        </MessageResponse>
                      </MessageContent>
                    </div>
                  ) : (
                    <div className="flex w-full gap-3">
                      <AmberMark className="mt-1 size-6 shrink-0" />
                      <MessageContent className="min-w-0 flex-1 overflow-visible">
                        <ToolElement tool={entry} />
                      </MessageContent>
                    </div>
                  )}
                </Message>
              ))
            )}
            {workspaceFile && (
              <details className="w-full rounded-xl border bg-card/60">
                <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
                  Source preview: {workspaceFile.title}
                </summary>
                {workspaceFile.driveUrl && (
                  <a
                    className="mx-4 text-xs text-primary underline-offset-4 hover:underline"
                    href={workspaceFile.driveUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open in Drive
                  </a>
                )}
                {workspaceFile.mimeType === "application/vnd.google-apps.spreadsheet" && workspaceFile.values ? (
                  <div className="max-h-64 overflow-auto p-4 pt-2">
                    <table className="w-full border-collapse text-left text-xs">
                      <tbody>
                        {workspaceFile.values.map((row, rowIndex) => (
                          <tr key={rowIndex}>
                            {row.map((value, columnIndex) => (
                              <td key={columnIndex} className="max-w-48 truncate border px-2 py-1">
                                {String(value ?? "")}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap p-4 pt-2 text-xs leading-5">
                    {workspaceFile.content}
                  </pre>
                )}
              </details>
            )}
            {approval && (
              <section className="w-full rounded-xl border border-primary/40 bg-primary/5 p-4">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <h2 className="text-sm font-semibold">Approval required: {approval.title}</h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      No Workspace changes happen until you approve this proposal.
                    </p>
                  </div>
                  {approval.url && (
                    <a
                      className="shrink-0 text-xs text-primary underline-offset-4 hover:underline"
                      href={approval.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open source
                    </a>
                  )}
                </div>
                <details className="mt-3">
                  <summary className="cursor-pointer text-xs font-medium">Review proposed change</summary>
                  {approval.before && (
                    <>
                      <div className="mt-2 text-[10px] font-semibold uppercase text-muted-foreground">Current</div>
                      <pre className="mt-1 max-h-36 overflow-auto whitespace-pre-wrap rounded bg-background p-3 text-xs">
                        {approval.before}
                      </pre>
                    </>
                  )}
                  <div className="mt-2 text-[10px] font-semibold uppercase text-muted-foreground">Proposed</div>
                  <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded bg-background p-3 text-xs">
                    {approval.after}
                  </pre>
                </details>
                <div className="mt-3 flex gap-2">
                  <Button
                    size="sm"
                    className="flex-1"
                    disabled={loading}
                    onClick={() => void respondToApproval("approve")}
                  >
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1"
                    disabled={loading}
                    onClick={() => void respondToApproval("reject")}
                  >
                    Reject
                  </Button>
                </div>
              </section>
            )}
            {loading && (
              <Message from="assistant" className="max-w-full">
                <div className="flex w-full gap-3">
                  <AmberMark className="mt-1 size-6 shrink-0" />
                  <MessageContent className="min-w-0 flex-1 overflow-visible">
                    <Shimmer duration={1}>Working through your request…</Shimmer>
                  </MessageContent>
                </div>
              </Message>
            )}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>

        <div className="border-t bg-background/40 p-3 sm:px-6 sm:py-4">
          <PromptInput
            onSubmit={({ text }) => send(text)}
            className="mx-auto max-w-4xl"
          >
            <PromptInputBody>
              <PromptInputTextarea
                value={draft}
                onChange={(event) => setDraft(event.currentTarget.value)}
                maxLength={2000}
                disabled={loading}
                placeholder="Message Amber…"
                className="min-h-12 max-h-40 text-[15px]"
              />
            </PromptInputBody>
            <PromptInputFooter className="border-t px-2 py-1.5">
              <PromptInputTools>
                {modelOptions?.enabled && (
                  <ModelSelector open={modelPickerOpen} onOpenChange={setModelPickerOpen}>
                    <ModelSelectorTrigger asChild>
                      <PromptInputButton
                        aria-label="Select model"
                        className="max-w-[min(20rem,60vw)] justify-start"
                      >
                        <Cpu className="size-3.5 shrink-0" />
                        <ModelSelectorName>
                          {selectedModel ?? `${modelOptions.default_model} · Default`}
                        </ModelSelectorName>
                        <ChevronDown className="size-3.5 shrink-0 opacity-60" />
                      </PromptInputButton>
                    </ModelSelectorTrigger>
                    <ModelSelectorContent title="Select a model">
                      <ModelSelectorInput placeholder="Search available models…" />
                      <ModelSelectorList>
                        <ModelSelectorEmpty>No matching models.</ModelSelectorEmpty>
                        <ModelSelectorGroup heading="Available models">
                          <ModelSelectorItem
                            value={`default ${modelOptions.default_model}`}
                            onSelect={() => {
                              setSelectedModel(null)
                              setModelPickerOpen(false)
                            }}
                          >
                            <ModelSelectorName>
                              {modelOptions.default_model} · Default
                            </ModelSelectorName>
                            {!selectedModel && <Check className="size-4" />}
                          </ModelSelectorItem>
                          {modelOptions.models
                            .filter((model) => model !== modelOptions.default_model)
                            .map((model) => (
                              <ModelSelectorItem
                                key={model}
                                value={model}
                                onSelect={() => {
                                  setSelectedModel(model)
                                  setModelPickerOpen(false)
                                }}
                              >
                                <ModelSelectorName>{model}</ModelSelectorName>
                                {selectedModel === model && <Check className="size-4" />}
                              </ModelSelectorItem>
                            ))}
                        </ModelSelectorGroup>
                      </ModelSelectorList>
                    </ModelSelectorContent>
                  </ModelSelector>
                )}
                <Select
                  key={selectedCollectionId ?? "all"}
                  defaultValue={selectedCollectionId ?? "all"}
                  value={selectedCollectionId ?? "all"}
                  onValueChange={(value) => setSelectedCollectionId(value === "all" ? null : value)}
                  disabled={collectionLoadError}
                >
                  <SelectTrigger aria-label="Filter by collection" className="max-w-[min(14rem,45vw)]">
                    <FolderOpen className="size-3.5 shrink-0" />
                    <SelectValue placeholder="All files" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All files</SelectItem>
                    {collections.map((collection) => (
                      <SelectItem key={collection.id} value={collection.id}>
                        {collection.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </PromptInputTools>
              <PromptInputSubmit
                status={loading ? "streaming" : "ready"}
                disabled={!draft.trim() || loading}
                className="shrink-0"
              />
            </PromptInputFooter>
          </PromptInput>
          {modelLoadError && (
            <p role="status" className="mx-auto mt-2 max-w-4xl text-center text-xs text-muted-foreground">
              Available models could not be loaded; Amber will use the configured default.
            </p>
          )}
          {collectionLoadError && (
            <p role="status" className="mx-auto mt-2 max-w-4xl text-center text-xs text-muted-foreground">
              Collections could not be loaded; searches will include all files.
            </p>
          )}
          <p className="mx-auto mt-2 max-w-4xl text-center text-[11px] text-muted-foreground">
            Enter to send · Shift + Enter for a new line
          </p>
        </div>
      </section>
      {sidekickOpen && (
        <button
          aria-label="Close Opal"
          className="fixed inset-0 z-40 bg-background/70 backdrop-blur-sm xl:hidden"
          onClick={() => setSidekickOpen(false)}
          type="button"
        />
      )}
      <aside
        className={cn(
          "min-w-0 flex-col gap-3 overflow-hidden",
          sidekickOpen
            ? "fixed inset-3 z-50 flex rounded-2xl border bg-background p-3 shadow-2xl xl:static xl:z-auto xl:border-0 xl:bg-transparent xl:p-0 xl:shadow-none"
            : "hidden xl:flex",
        )}
      >
        <Queue className="min-h-0">
          <QueueSection defaultOpen>
            <QueueSectionTrigger>
              <QueueSectionLabel label="Tasks" count={tasks.length} />
            </QueueSectionTrigger>
            <QueueSectionContent>
              <QueueList className="max-h-56">
                {tasks.map((task) => (
                  <QueueItem key={task.id} className="flex-row items-center">
                    <QueueItemIndicator
                      completed={task.status === "completed"}
                      className={
                        task.status === "in_progress"
                          ? "animate-pulse border-primary bg-primary/30"
                          : task.status === "failed"
                            ? "border-destructive bg-destructive/30"
                            : undefined
                      }
                    />
                    <QueueItemContent
                      completed={task.status === "completed"}
                      className={task.status === "in_progress" ? "text-foreground" : undefined}
                    >
                      {task.title}
                    </QueueItemContent>
                  </QueueItem>
                ))}
                {tasks.length === 0 && (
                  <li className="px-3 py-2 text-xs text-muted-foreground">
                    Tasks will appear as the agent works.
                  </li>
                )}
              </QueueList>
            </QueueSectionContent>
          </QueueSection>
        </Queue>
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="mb-2 flex justify-end xl:hidden">
            <Button
              aria-label="Close Opal"
              onClick={() => setSidekickOpen(false)}
              size="icon-sm"
              variant="ghost"
            >
              <X className="size-4" />
            </Button>
          </div>
          <LiveSidekick
            key={sidekickSession}
            context={sidekickContext}
            draft={draft}
            onDraftChange={setDraft}
          />
        </div>
      </aside>
      <Button
        className="fixed bottom-20 right-4 z-30 shadow-lg xl:hidden"
        onClick={() => setSidekickOpen(true)}
        size="sm"
      >
        <MessageSquare className="mr-1 size-4" />
        Talk to Opal
      </Button>
      <Dialog
        open={editingId !== null}
        onOpenChange={(open) => {
          if (!open && savingConversationId === null) {
            setEditingId(null)
          }
        }}
      >
        <DialogContent>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (editingId) void saveRename(editingId)
            }}
          >
            <DialogHeader>
              <DialogTitle>Rename conversation</DialogTitle>
              <DialogDescription>
                Choose a name that will help you find this conversation later.
              </DialogDescription>
            </DialogHeader>
            <Input
              autoFocus
              aria-label="Conversation name"
              value={editingTitle}
              maxLength={255}
              onChange={(event) => setEditingTitle(event.currentTarget.value)}
              className="my-4"
            />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditingId(null)}
                disabled={savingConversationId !== null}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={!editingTitle.trim() || savingConversationId !== null}
              >
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
