"use client"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { demoAction, useDemo } from "@/lib/demo"
import { initials } from "@/lib/format"
import type { User } from "@/lib/types"
import { cn } from "@/lib/utils"

// Loaded from the admin API once it exists.
const users: User[] = []

export function UsersTab() {
  const { user: me } = useDemo()
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Anyone with a Google account can sign in and starts as a Member. Admins can manage documents, users and settings.
      </p>
      <div className="overflow-hidden rounded-2xl border bg-card/40">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">User</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last active</TableHead>
              <TableHead className="text-right">Documents</TableHead>
              <TableHead className="w-32" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((user) => {
              const isSelf = user.id === me?.id
              const active = user.status === "active"
              return (
                <TableRow key={user.id} className={cn(!active && "opacity-60")}>
                  <TableCell className="pl-4">
                    <div className="flex items-center gap-2.5">
                      <Avatar className="size-8">
                        <AvatarFallback className="text-xs">{initials(user.name)}</AvatarFallback>
                      </Avatar>
                      <div>
                        <div className="font-medium">
                          {user.name}
                          {isSelf && <span className="ml-1.5 text-xs text-muted-foreground">(you)</span>}
                        </div>
                        <div className="text-xs text-muted-foreground">{user.email}</div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Select
                      defaultValue={user.role}
                      disabled={isSelf}
                      onValueChange={(role) => demoAction(`Role changed to ${role}`, `${user.email}. Demo only.`)}
                    >
                      <SelectTrigger className="h-8 w-28" aria-label={`Role for ${user.email}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="admin">Admin</SelectItem>
                        <SelectItem value="member">Member</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <span className="inline-flex items-center gap-1.5 text-sm">
                      <span className={cn("size-1.5 rounded-full", active ? "bg-success" : "bg-muted-foreground")} aria-hidden="true" />
                      {active ? "Active" : "Deactivated"}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{user.lastActive}</TableCell>
                  <TableCell className="text-right tabular-nums">{user.documentCount}</TableCell>
                  <TableCell className="pr-4 text-right">
                    {!isSelf && (
                      <Button
                        variant={active ? "ghost" : "outline"}
                        size="sm"
                        className={cn(active && "text-destructive hover:text-destructive")}
                        onClick={() => demoAction(active ? "User deactivated" : "User reactivated", user.email)}
                      >
                        {active ? "Deactivate" : "Reactivate"}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
            {users.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                  No users have signed in yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
