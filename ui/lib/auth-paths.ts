// Shared by server and client code. Cookie names mirror cookie_names() in amber/util/security.py:
// `__Host-` over https, plain names over http (local dev) or when AMBER_COOKIE_SECURE=false.
export const SESSION_COOKIES = ["__Host-amber_session", "amber_session"]
export const CSRF_COOKIES = ["__Host-amber_csrf", "amber_csrf"]

/** App-relative paths only, so a crafted `return_to` can't send users to another site. */
export function safeReturnTo(value: string | null | undefined): string {
  return value && /^\/(?!\/|\\|api(?:\/|$))[A-Za-z0-9\-._~/?=&%]*$/.test(value) ? value : "/search"
}

/** Starts Google sign-in. A plain link: the API redirects to Google's consent screen. */
export function googleSignInUrl(returnTo: string, opts: { reconnect?: boolean } = {}): string {
  const params = new URLSearchParams({ return_to: safeReturnTo(returnTo) })
  if (opts.reconnect) params.set("reconnect", "true")
  return `/api/auth/google/start?${params}`
}
