"use client"

import Link from "next/link"
import { LogIn, LogOut, ShieldCheck, User as UserIcon, Users } from "lucide-react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { demoAction, useDemo } from "@/lib/demo"
import { initials } from "@/lib/format"
import type { Role } from "@/lib/types"

export function UserMenu() {
  const { user, role, setRole } = useDemo()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-9 gap-2 rounded-full pr-3 pl-1" aria-label="Account menu">
          <Avatar className="size-7">
            <AvatarFallback className="bg-primary/15 text-xs font-semibold text-primary">
              {user ? initials(user.name) : <UserIcon className="size-4" />}
            </AvatarFallback>
          </Avatar>
          <span className="hidden text-sm sm:inline">{user ? user.name.split(" ")[0] : "Account"}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-medium">{user?.name ?? "Not signed in"}</span>
            {user && <span className="text-xs text-muted-foreground">{user.email}</span>}
            <Badge variant="outline" className="mt-1.5 w-fit capitalize">
              {role === "admin" ? <ShieldCheck /> : <UserIcon />}
              {role}
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
        <DropdownMenuLabel className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Users className="size-3.5" /> Demo: view as
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={role} onValueChange={(value) => setRole(value as Role)}>
          <DropdownMenuRadioItem value="admin">Admin</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="member">Member</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          {user ? (
            <Link href="/login" onClick={() => demoAction("Signed out")}>
              <LogOut /> Sign out
            </Link>
          ) : (
            <Link href="/login">
              <LogIn /> Sign in
            </Link>
          )}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
