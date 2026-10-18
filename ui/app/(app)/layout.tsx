import { TopNav } from "@/components/app/top-nav"
import { requireUser } from "@/lib/session"
import { SessionProvider } from "@/lib/session-context"

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await requireUser()
  return (
    <SessionProvider user={user}>
      <TopNav />
      <main className="w-full flex-1 flex flex-col px-4 py-3 sm:px-6 sm:py-4 overflow-hidden">{children}</main>
    </SessionProvider>
  )
}
