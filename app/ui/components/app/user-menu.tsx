"use client"

import Link from "next/link"
import { LogOut, ShieldCheck, User as UserIcon, Users } from "lucide-react"

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
import { currentUser } from "@/lib/mock-data"
import type { Role } from "@/lib/types"

export function UserMenu() {
  const { role, setRole } = useDemo()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-9 gap-2 rounded-full pr-3 pl-1" aria-label="Account menu">
          <Avatar className="size-7">
            <AvatarFallback className="bg-primary/15 text-xs font-semibold text-primary">
              {initials(currentUser.name)}
            </AvatarFallback>
          </Avatar>
          <span className="hidden text-sm sm:inline">{currentUser.name.split(" ")[0]}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-medium">{currentUser.name}</span>
            <span className="text-xs text-muted-foreground">{currentUser.email}</span>
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
          <Link href="/login" onClick={() => demoAction("Signed out")}>
            <LogOut /> Sign out
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
