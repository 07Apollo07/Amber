import { CSRF_COOKIES } from "./auth-paths"

function readCsrfToken(): string {
  const cookies = new Map(
    document.cookie.split("; ").map((pair) => {
      const at = pair.indexOf("=")
      return [pair.slice(0, at), decodeURIComponent(pair.slice(at + 1))] as const
    }),
  )
  return CSRF_COOKIES.map((name) => cookies.get(name)).find(Boolean) ?? ""
}

/** State-changing call to the API. Sends the double-submit CSRF token the API requires. */
export async function apiPost(path: string, body?: unknown): Promise<Response> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "X-Amber-CSRF": readCsrfToken(),
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `Request failed (${res.status})`)
  }
  return res
}
