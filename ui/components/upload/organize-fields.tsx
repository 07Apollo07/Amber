"use client"

import { useState } from "react"
import { Plus } from "lucide-react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { cn } from "@/lib/utils"

export function OrganizeFields({
  collection,
  onCollectionChange,
  tags,
  onTagsChange,
  collections = [],
  knownTags = [],
  idPrefix = "",
  showCollection = true,
}: {
  collection: string
  onCollectionChange: (value: string) => void
  tags: string[]
  onTagsChange: (value: string[]) => void
  /** The user's existing collections. */
  collections?: string[]
  /** Tags already used on the user's documents, offered as one-click options. */
  knownTags?: string[]
  /** Keeps element ids unique when this form is on the page more than once. */
  idPrefix?: string
  showCollection?: boolean
}) {
  const [addedTags, setAddedTags] = useState<string[]>([])
  const tagOptions = [...new Set([...knownTags, ...addedTags, ...tags])]
  const [draft, setDraft] = useState("")
  const [newCollection, setNewCollection] = useState("")
  const collectionOptions = collection !== "none" && !collections.includes(collection) ? [...collections, collection] : collections

  function addCollection() {
    const name = newCollection.trim().slice(0, 255)
    if (!name) return
    onCollectionChange(name)
    setNewCollection("")
  }

  function toggle(tag: string) {
    onTagsChange(tags.includes(tag) ? tags.filter((t) => t !== tag) : [...tags, tag])
  }

  function addTag() {
    const tag = draft.trim().toLowerCase().replace(/[^a-z0-9-]/g, "-").slice(0, 32)
    if (!tag) return
    if (!tagOptions.includes(tag)) setAddedTags((t) => [...t, tag])
    if (!tags.includes(tag)) onTagsChange([...tags, tag])
    setDraft("")
  }

  return (
    <div className="space-y-4">
      {showCollection && <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}collection`}>Collection</Label>
        <Select value={collection} onValueChange={onCollectionChange}>
          <SelectTrigger id={`${idPrefix}collection`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">No collection</SelectItem>
            {collectionOptions.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          value={newCollection}
          onChange={(event) => setNewCollection(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              addCollection()
            }
          }}
          onBlur={addCollection}
          placeholder="Or create a new collection"
          aria-label="New collection name"
        />
      </div>}
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}new-tag`}>Tags</Label>
        <div className="flex flex-wrap gap-1.5">
          {tagOptions.length === 0 && <p className="text-xs text-muted-foreground">No tags yet. Add one below.</p>}
          {tagOptions.map((tag) => {
            const on = tags.includes(tag)
            return (
              <button
                key={tag}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(tag)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                  on ? "border-primary/50 bg-primary/15 text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                #{tag}
              </button>
            )
          })}
        </div>
        <div className="relative">
          <Input
            id={`${idPrefix}new-tag`}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault()
                addTag()
              }
            }}
            placeholder="New tag"
            className="pr-9"
          />
          <button
            type="button"
            onClick={addTag}
            aria-label="Add tag"
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
          >
            <Plus className="size-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
