import { NextRequest } from "next/server"

export async function GET(req: NextRequest) {
  try {
    const api = process.env.AMBER_API_ORIGIN ?? "http://127.0.0.1:8000"
    const backendRes = await fetch(`${api}/api/agent/models`, {
      headers: {
        Cookie: req.headers.get("cookie") || "",
      },
      cache: "no-store",
    })
    const body = await backendRes.text()
    return new Response(body, {
      status: backendRes.status,
      headers: {
        "Content-Type": backendRes.headers.get("content-type") || "application/json",
        "Cache-Control": "no-store",
      },
    })
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unable to load available models"
    return Response.json({ detail }, { status: 502 })
  }
}
