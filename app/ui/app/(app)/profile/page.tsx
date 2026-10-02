import type { Metadata } from "next"

import { PageHeader } from "@/components/app/page-header"
import { ProfilePage } from "@/components/profile/profile-page"

export const metadata: Metadata = { title: "Profile" }

export default function Page() {
  return (
    <>
      <PageHeader title="Profile" description="Your account, Google Drive connection, documents and history." />
      <ProfilePage />
    </>
  )
}
