"use client"

import Link from "next/link"
import { LogOut, ShieldCheck, User as UserIcon } from "lucide-react"

import { UserAvatar } from "@/components/app/user-avatar"
import { useSignOut } from "@/components/app/sign-out"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useSession } from "@/lib/session-context"

export function UserMenu() {
  const user = useSession()
  const { signOut, pending } = useSignOut()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-9 gap-2 rounded-full pr-3 pl-1" aria-label="Account menu">
          <UserAvatar user={user} className="size-7 text-xs" />
          <span className="hidden text-sm sm:inline">{user.name.split(" ")[0]}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col gap-0.5">
            <span className="truncate text-sm font-medium">{user.name}</span>
            <span className="truncate text-xs text-muted-foreground">{user.email}</span>
            <Badge variant="outline" className="mt-1.5 w-fit capitalize">
              {user.role === "admin" ? <ShieldCheck /> : <UserIcon />}
              {user.role}
            </Badge>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/profile">
            <UserIcon /> Profile
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled={pending} onSelect={() => signOut()}>
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
