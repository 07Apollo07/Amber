"use client"

import { useState } from "react"
import { Download, Search } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { demoAction } from "@/lib/demo"
import { auditEvents } from "@/lib/mock-data"

const actors = Array.from(new Set(auditEvents.map((e) => e.actor)))
const actions = Array.from(new Set(auditEvents.map((e) => e.action)))

export function AuditTab() {
  const [actor, setActor] = useState("all")
  const [action, setAction] = useState("all")
  const [text, setText] = useState("")

  const rows = auditEvents.filter(
    (e) =>
      (actor === "all" || e.actor === actor) &&
      (action === "all" || e.action === action) &&
      `${e.target} ${e.detail}`.toLowerCase().includes(text.toLowerCase()),
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={actor} onValueChange={setActor}>
          <SelectTrigger className="w-48" aria-label="Filter by user">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All users</SelectItem>
            {actors.map((a) => (
              <SelectItem key={a} value={a}>
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={action} onValueChange={setAction}>
          <SelectTrigger className="w-48" aria-label="Filter by action">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All actions</SelectItem>
            {actions.map((a) => (
              <SelectItem key={a} value={a}>
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="relative w-56">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Document or detail" className="pl-8" aria-label="Filter by document" />
        </div>
        <Button variant="outline" className="ml-auto" onClick={() => demoAction("Export CSV")}>
          <Download /> Export CSV
        </Button>
      </div>
      <div className="overflow-hidden rounded-2xl border bg-card/40">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Time</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Target</TableHead>
              <TableHead>Detail</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="pl-4 whitespace-nowrap text-muted-foreground tabular-nums">{e.at}</TableCell>
                <TableCell>{e.actor}</TableCell>
                <TableCell>
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{e.action}</code>
                </TableCell>
                <TableCell className="max-w-[220px] truncate">{e.target}</TableCell>
                <TableCell className="text-muted-foreground">{e.detail}</TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="py-10 text-center text-muted-foreground">
                  No events match these filters.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">The audit log is append-only. Entries can&apos;t be edited or deleted.</p>
    </div>
  )
}
