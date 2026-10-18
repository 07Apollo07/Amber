"use client"

import { useCallback, useEffect, useState } from "react"

/** Loads an admin endpoint and lets the caller reload it after a change. */
export function useAdminData<T>(path: string) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetch(path, { credentials: "same-origin" })
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Request failed (${res.status})`)
        return (await res.json()) as T
      })
      .then((json) => {
        if (cancelled) return
        setData(json)
        setError(null)
      })
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [path, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, error, reload }
}
