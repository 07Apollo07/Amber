import Link from "next/link"

import { AmberMark } from "@/components/app/amber-logo"
import { Button } from "@/components/ui/button"

export default function NotFound() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center px-4 text-center">
      <AmberMark className="mb-4 size-10 opacity-80" />
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-muted-foreground">That page doesn&apos;t exist or was moved.</p>
      <Button asChild className="mt-6">
        <Link href="/search">Go to search</Link>
      </Button>
    </main>
  )
}
