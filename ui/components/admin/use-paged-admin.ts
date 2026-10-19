"use client"

import { useCallback, useEffect, useRef, useState } from "react"

type Page<T> = { items: T[]; next: string | number | null; raw: Record<string, unknown> }

/**
 * Loads a cursor-paginated admin list. A new `query` (filters) starts over; `loadMore` appends the next page.
 * `key` names the array in the response (e.g. "events").
 */
export function usePagedAdmin<T>(path: string, key: string, query: Record<string, string | undefined>) {
  const [items, setItems] = useState<T[]>([])
  const [raw, setRaw] = useState<Record<string, unknown> | null>(null)
  const [next, setNext] = useState<string | number | null>(null)
  const [settled, setSettled] = useState<string | null>(null) // which first page last finished loading
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const request = useRef(0)

  const search = new URLSearchParams(
    Object.entries(query).filter((entry): entry is [string, string] => Boolean(entry[1])),
  ).toString()

  const fetchPage = useCallback(
    async (before: string | number | null): Promise<Page<T>> => {
      const params = new URLSearchParams(search)
      if (before !== null) params.set("before", String(before))
      const res = await fetch(`${path}?${params}`, { credentials: "same-origin", cache: "no-store" })
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Request failed (${res.status})`)
      const json = (await res.json()) as Record<string, unknown>
      return { items: (json[key] as T[]) ?? [], next: (json.next as string | number | null) ?? null, raw: json }
    },
    [path, key, search],
  )

  const current = `${search}#${nonce}`
  const loading = settled !== current || loadingMore

  useEffect(() => {
    const id = ++request.current
    fetchPage(null)
      .then((page) => {
        if (id !== request.current) return
        setItems(page.items)
        setNext(page.next)
        setRaw(page.raw)
        setError(null)
      })
      .catch((err: Error) => id === request.current && setError(err.message))
      .finally(() => id === request.current && setSettled(current))
  }, [fetchPage, current])

  const loadMore = useCallback(async () => {
    if (next === null || loading) return
    const id = ++request.current
    setLoadingMore(true)
    try {
      const page = await fetchPage(next)
      if (id !== request.current) return
      setItems((existing) => [...existing, ...page.items])
      setNext(page.next)
    } catch (err) {
      if (id === request.current) setError((err as Error).message)
    } finally {
      setLoadingMore(false)
    }
  }, [fetchPage, loading, next])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { items, raw, hasMore: next !== null, loading, error, loadMore, reload, search }
}

/** The value after the user stops typing for `ms`. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timeout = window.setTimeout(() => setDebounced(value), ms)
    return () => window.clearTimeout(timeout)
  }, [value, ms])
  return debounced
}

export type RangePreset = "24h" | "7d" | "30d" | "90d" | "all"

export const rangeLabel: Record<RangePreset, string> = {
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  all: "All time",
}

/** ISO start time for a preset, computed once when the preset is picked. */
export function rangeStart(preset: RangePreset): string | undefined {
  const hours = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30, "90d": 24 * 90, all: 0 }[preset]
  return hours ? new Date(Date.now() - hours * 3_600_000).toISOString() : undefined
}
