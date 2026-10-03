import { TopNav } from "@/components/app/top-nav"
import { requireUser } from "@/lib/session"
import { SessionProvider } from "@/lib/session-context"

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await requireUser()
  return (
    <SessionProvider user={user}>
      <TopNav />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8">{children}</main>
    </SessionProvider>
  )
}
