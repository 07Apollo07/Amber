import type { Metadata } from "next"
import Link from "next/link"
import { ShieldAlert } from "lucide-react"

import { AdminPage } from "@/components/admin/admin-page"
import { PageHeader } from "@/components/app/page-header"
import { Button } from "@/components/ui/button"
import { requireUser } from "@/lib/session"

export const metadata: Metadata = { title: "Admin" }

export default async function Page() {
  // Role comes from Postgres via /api/me. Every /api/admin/* endpoint enforces it again.
  const user = await requireUser()
  if (user.role !== "admin") {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center py-20 text-center">
        <ShieldAlert className="mb-4 size-10 text-muted-foreground" />
        <h1 className="text-xl font-semibold">Admins only</h1>
        <p className="mt-2 text-sm text-muted-foreground">You don&apos;t have access to this page. Ask an admin if you need it.</p>
        <Button asChild className="mt-6">
          <Link href="/search">Back to search</Link>
        </Button>
      </div>
    )
  }

  return (
    <>
      <PageHeader title="Admin" description="Manage documents, users, access and how Amber answers." />
      <AdminPage />
    </>
  )
}
