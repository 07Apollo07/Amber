"use client"

import { useState } from "react"
import { Trash2, UserPlus } from "lucide-react"
import { toast } from "sonner"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiDelete, apiPost, apiPut } from "@/lib/api"
import { initials } from "@/lib/format"
import { useSession } from "@/lib/session-context"
import { cn } from "@/lib/utils"

import { useAdminData } from "./use-admin-data"

type AdminUser = {
  id: string
  email: string
  name: string
  role: "admin" | "member"
  status: "active" | "deactivated"
  pending: boolean
  created_at: string | null
  last_login_at: string | null
  document_count: number
}

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : null
}

export function UsersTab() {
  const me = useSession()
  const { data, error, reload } = useAdminData<{ users: AdminUser[] }>("/api/admin/users")
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<AdminUser | null>(null)
  const users = data?.users ?? []

  async function change(user: AdminUser, next: Partial<Pick<AdminUser, "role" | "status">>, message: string) {
    try {
      await apiPut(`/api/admin/users/${user.id}`, { role: user.role, status: user.status, ...next })
      toast.success(message, { description: user.email })
      reload()
    } catch (err) {
      toast.error("Couldn't update user", { description: (err as Error).message })
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-xl text-sm text-muted-foreground">
          Anyone with a Google account can sign in and starts as a Member. Add someone here to set their role before they
          first sign in.
        </p>
        <Button onClick={() => setAdding(true)}>
          <UserPlus /> Add user
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          Couldn&apos;t load users: {error}
        </p>
      )}
      <div className="overflow-hidden rounded-2xl border bg-card/40">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">User</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last sign-in</TableHead>
              <TableHead className="text-right">Documents</TableHead>
              <TableHead className="w-48" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((user) => {
              const isSelf = user.id === me.id
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
                      value={user.role}
                      disabled={isSelf}
                      onValueChange={(role) => change(user, { role: role as AdminUser["role"] }, `Role changed to ${role}`)}
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
                      {!active ? "Deactivated" : user.pending ? "Invited" : "Active"}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{when(user.last_login_at) ?? "Never"}</TableCell>
                  <TableCell className="text-right tabular-nums">{user.document_count}</TableCell>
                  <TableCell className="pr-4 text-right">
                    {!isSelf && (
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            change(user, { status: active ? "deactivated" : "active" }, active ? "User deactivated" : "User reactivated")
                          }
                        >
                          {active ? "Deactivate" : "Reactivate"}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          className="text-destructive hover:text-destructive"
                          aria-label={`Delete ${user.email}`}
                          onClick={() => setRemoving(user)}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
            {data && users.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                  No users yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <AddUserDialog open={adding} onOpenChange={setAdding} onAdded={reload} />

      <Dialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {removing?.email}?</DialogTitle>
            <DialogDescription>
              This removes the account and everything they own in Amber: {removing?.document_count ?? 0} document
              {removing?.document_count === 1 ? "" : "s"}, their search index entries, collections and Drive connection. Files in
              their Google Drive are not touched. If they sign in again they start over as a new Member. To block someone instead,
              deactivate them.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={async () => {
                if (!removing) return
                try {
                  await apiDelete(`/api/admin/users/${removing.id}`)
                  toast.success("User deleted", { description: removing.email })
                  reload()
                } catch (err) {
                  toast.error("Couldn't delete user", { description: (err as Error).message })
                }
                setRemoving(null)
              }}
            >
              Delete user
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function AddUserDialog({
  open,
  onOpenChange,
  onAdded,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onAdded: () => void
}) {
  const [email, setEmail] = useState("")
  const [name, setName] = useState("")
  const [role, setRole] = useState("member")
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await apiPost("/api/admin/users", { email, name, role })
      toast.success("User added", { description: `${email} can now sign in with Google.` })
      setEmail("")
      setName("")
      setRole("member")
      onOpenChange(false)
      onAdded()
    } catch (err) {
      toast.error("Couldn't add user", { description: (err as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Add user</DialogTitle>
            <DialogDescription>
              They sign in with this Google account. Their name is filled in from Google the first time they do.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="new-user-email">Email</Label>
            <Input id="new-user-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="new-user-name">Name (optional)</Label>
            <Input id="new-user-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="new-user-role">Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger id="new-user-role" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="member">Member</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !email.trim()}>
              Add user
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
