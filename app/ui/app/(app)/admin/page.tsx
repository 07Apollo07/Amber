import type { Metadata } from "next"

import { AdminPage } from "@/components/admin/admin-page"
import { PageHeader } from "@/components/app/page-header"

export const metadata: Metadata = { title: "Admin" }

export default function Page() {
  return (
    <>
      <PageHeader title="Admin" description="Manage documents, users, access and how Amber answers." />
      <AdminPage />
    </>
  )
}
