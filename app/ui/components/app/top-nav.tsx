"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Search, Shield, Upload } from "lucide-react"

import { AmberLogo } from "@/components/app/amber-logo"
import { UserMenu } from "@/components/app/user-menu"
import { useDemo } from "@/lib/demo"
import { cn } from "@/lib/utils"

const links = [
  { href: "/search", label: "Search", icon: Search, adminOnly: false },
  { href: "/upload", label: "Upload", icon: Upload, adminOnly: false },
  { href: "/admin", label: "Admin", icon: Shield, adminOnly: true },
]

export function TopNav() {
  const pathname = usePathname()
  const { role } = useDemo()

  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/75 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-4 sm:gap-6 sm:px-6">
        <Link href="/search" aria-label="Amber home" className="shrink-0">
          <AmberLogo />
        </Link>
        <nav aria-label="Main" className="flex items-center gap-1">
          {links
            .filter((link) => !link.adminOnly || role === "admin")
            .map(({ href, label, icon: Icon }) => {
              const active = pathname.startsWith(href)
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground",
                    active && "bg-muted text-foreground",
                  )}
                >
                  <Icon className={cn("size-4", active && "text-primary")} />
                  <span className="hidden sm:inline">{label}</span>
                </Link>
              )
            })}
        </nav>
        <div className="ml-auto">
          <UserMenu />
        </div>
      </div>
    </header>
  )
}
