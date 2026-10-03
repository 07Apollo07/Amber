"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "sonner"

import { apiPost } from "@/lib/api"

/** Signs out of this browser, or (`everywhere`) revokes every session for the account. */
export function useSignOut() {
  const router = useRouter()
  const [pending, setPending] = useState(false)

  async function signOut(everywhere = false) {
    setPending(true)
    try {
      await apiPost(everywhere ? "/api/auth/logout-all" : "/api/auth/logout")
      router.replace("/login")
      router.refresh()
    } catch {
      toast.error("Couldn't sign out", { description: "Please try again." })
      setPending(false)
    }
  }

  return { signOut, pending }
}
