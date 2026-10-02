"use client"

import { Calendar, ChevronDown, FileType2, FolderOpen, Layers, X } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { fileTypeLabel } from "@/lib/format"
import { allTags, collections } from "@/lib/mock-data"
import type { FileType } from "@/lib/types"
import { cn } from "@/lib/utils"

export type Filters = {
  sources: string[]
  collections: string[]
  fileTypes: string[]
  dateRange: string
}

export const emptyFilters: Filters = { sources: [], collections: [], fileTypes: [], dateRange: "any" }

const sourceOptions = [
  { value: "desktop_upload", label: "Uploaded files" },
  { value: "drive_picker", label: "Google Drive" },
]
const collectionOptions = [
  ...collections.map((c) => ({ value: c, label: c })),
  ...allTags.map((t) => ({ value: `#${t}`, label: `#${t}` })),
]
const fileTypeOptions = (Object.keys(fileTypeLabel) as FileType[]).map((t) => ({ value: t, label: fileTypeLabel[t] }))

function MultiFilter({
  label,
  icon: Icon,
  options,
  selected,
  onChange,
}: {
  label: string
  icon: LucideIcon
  options: { value: string; label: string }[]
  selected: string[]
  onChange: (next: string[]) => void
}) {
  const active = selected.length > 0
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn("h-8 rounded-full", active && "border-primary/50 bg-primary/10 text-foreground")}
        >
          <Icon className={cn(active && "text-primary")} />
          {label}
          {active && <span className="rounded-full bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">{selected.length}</span>}
          <ChevronDown className="opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-60 p-1.5">
        <div className="max-h-72 overflow-y-auto">
          {options.map((option) => {
            const checked = selected.includes(option.value)
            const id = `filter-${label}-${option.value}`
            return (
              <label
                key={option.value}
                htmlFor={id}
                className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
              >
                <Checkbox
                  id={id}
                  checked={checked}
                  onCheckedChange={(value) =>
                    onChange(value ? [...selected, option.value] : selected.filter((v) => v !== option.value))
                  }
                />
                {option.label}
              </label>
            )
          })}
        </div>
        {active && (
          <Button variant="ghost" size="sm" className="mt-1 w-full" onClick={() => onChange([])}>
            Clear
          </Button>
        )}
      </PopoverContent>
    </Popover>
  )
}

export function FilterBar({ filters, onChange }: { filters: Filters; onChange: (next: Filters) => void }) {
  const activeCount =
    filters.sources.length + filters.collections.length + filters.fileTypes.length + (filters.dateRange !== "any" ? 1 : 0)

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Search filters">
      <Select value={filters.dateRange} onValueChange={(dateRange) => onChange({ ...filters, dateRange })}>
        <SelectTrigger
          className={cn("h-8 rounded-full", filters.dateRange !== "any" && "border-primary/50 bg-primary/10")}
          aria-label="Date range"
        >
          <Calendar className={cn(filters.dateRange !== "any" && "text-primary")} />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="any">Any time</SelectItem>
          <SelectItem value="7d">Past 7 days</SelectItem>
          <SelectItem value="30d">Past 30 days</SelectItem>
          <SelectItem value="90d">Past 90 days</SelectItem>
          <SelectItem value="1y">Past year</SelectItem>
        </SelectContent>
      </Select>
      <MultiFilter
        label="Source"
        icon={FolderOpen}
        options={sourceOptions}
        selected={filters.sources}
        onChange={(sources) => onChange({ ...filters, sources })}
      />
      <MultiFilter
        label="Collections & tags"
        icon={Layers}
        options={collectionOptions}
        selected={filters.collections}
        onChange={(next) => onChange({ ...filters, collections: next })}
      />
      <MultiFilter
        label="File type"
        icon={FileType2}
        options={fileTypeOptions}
        selected={filters.fileTypes}
        onChange={(fileTypes) => onChange({ ...filters, fileTypes })}
      />
      {activeCount > 0 && (
        <Button variant="ghost" size="sm" className="h-8 rounded-full text-muted-foreground" onClick={() => onChange(emptyFilters)}>
          <X /> Clear all
        </Button>
      )}
    </div>
  )
}
