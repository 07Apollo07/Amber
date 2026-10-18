import Link from "next/link"

import { AmberMark } from "@/components/app/amber-logo"

// Public pages (no sign-in needed): /privacy and /terms.
export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="border-b">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
          <Link href="/login" className="flex items-center gap-2 font-semibold">
            <AmberMark className="size-6" />
            Amber
          </Link>
          <Link href="/login" className="text-sm text-muted-foreground hover:text-foreground">
            Sign in
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10">{children}</main>
      <footer className="border-t py-6 text-center text-xs text-muted-foreground">
        <Link href="/privacy" className="hover:text-foreground">Privacy Policy</Link>
        <span className="mx-2">·</span>
        <Link href="/terms" className="hover:text-foreground">Terms and Conditions</Link>
      </footer>
    </>
  )
}
