import { NextResponse, type NextRequest } from "next/server"

import { SESSION_COOKIES } from "@/lib/auth-paths"

const PROTECTED = ["/search", "/upload", "/profile", "/admin"]

/**
 * 1. Optimistic route guard: signed-in pages need a session cookie, otherwise go to /login.
 *    The real check (cookie signature, revocation, role) happens in the API via requireUser().
 * 2. Per-request nonce-based Content-Security-Policy. Next.js reads the nonce from the
 *    request header and applies it to its own scripts.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl
  const needsSession = pathname === "/" || PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`))
  if (needsSession && !SESSION_COOKIES.some((name) => request.cookies.has(name))) {
    const login = new URL("/login", request.url)
    if (pathname !== "/") login.searchParams.set("return_to", pathname + search)
    return NextResponse.redirect(login)
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64")
  const isDev = process.env.NODE_ENV === "development"

  const csp = [
    "default-src 'self'",
    // 'wasm-unsafe-eval' lets the Opal persona compile Rive's self-hosted WebAssembly; it does not allow JS eval.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' 'wasm-unsafe-eval' https://apis.google.com${isDev ? " 'unsafe-eval'" : ""}`,
    // Radix positions popovers with inline style attributes, which nonces can't cover.
    "style-src 'self' 'unsafe-inline' https://www.gstatic.com https://ssl.gstatic.com",
    // The Google Picker (Drive file chooser) loads its script, frame, styles and thumbnails from Google.
    "img-src 'self' blob: data: https://lh3.googleusercontent.com https://*.googleusercontent.com https://ssl.gstatic.com https://www.gstatic.com",
    "frame-src https://docs.google.com https://drive.google.com https://content.googleapis.com https://accounts.google.com",
    "font-src 'self'",
    `connect-src 'self' https://apis.google.com https://content.googleapis.com${isDev ? " ws:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(isDev ? [] : ["upgrade-insecure-requests"]),
  ].join("; ")

  const requestHeaders = new Headers(request.headers)
  requestHeaders.set("x-nonce", nonce)
  requestHeaders.set("Content-Security-Policy", csp)

  const response = NextResponse.next({ request: { headers: requestHeaders } })
  response.headers.set("Content-Security-Policy", csp)
  return response
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
}
