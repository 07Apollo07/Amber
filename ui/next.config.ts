import type { NextConfig } from "next"

const securityHeaders = [
  // No `preload`: getting onto the browsers' preload list is effectively permanent. Add it only
  // once every subdomain is confirmed HTTPS-only.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
]

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }]
  },
  // Web and API share one origin. In production the load balancer sends /api/* to FastAPI
  // before it reaches Next.js; locally this rewrite does the same, so cookies stay first-party.
  async rewrites() {
    const api = process.env.AMBER_API_ORIGIN ?? "http://127.0.0.1:8000"
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }]
  },
}

export default nextConfig
