import type { Metadata } from "next"

import { PageHeader } from "@/components/app/page-header"
import { UploadPage } from "@/components/upload/upload-page"

export const metadata: Metadata = { title: "Data" }

export default function Page() {
  return (
    <>
      <PageHeader title="Data" description="Add documents from your computer or Google Drive so Amber can answer from them." />
      <UploadPage />
    </>
  )
}
