import { NextRequest } from "next/server"

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const api = process.env.AMBER_API_ORIGIN ?? "http://127.0.0.1:8000"
    
    const cookie = req.headers.get("cookie") || ""
    const csrf = req.headers.get("x-amber-csrf") || ""

    const backendRes = await fetch(`${api}/api/agent/v2/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Cookie": cookie,
        "X-Amber-CSRF": csrf,
      },
      body: JSON.stringify(body),
    })

    if (!backendRes.ok || !backendRes.body) {
      const errText = await backendRes.text().catch(() => "Unknown error")
      return new Response(JSON.stringify({ detail: errText }), {
        status: backendRes.status,
        headers: { "Content-Type": "application/json" },
      })
    }

    return new Response(backendRes.body, {
      status: backendRes.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
      },
    })
  } catch (error: any) {
    return new Response(JSON.stringify({ detail: error?.message || "Internal server error" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    })
  }
}
