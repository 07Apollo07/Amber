"use client"

import { BarChart3, FileText, History, Route, Settings, ShieldAlert, Users } from "lucide-react"
import Link from "next/link"

import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useDemo } from "@/lib/demo"

import { AnalyticsTab } from "./analytics-tab"
import { AuditTab } from "./audit-tab"
import { DocumentsTab } from "./documents-tab"
import { SettingsTab } from "./settings-tab"
import { TracesTab } from "./traces-tab"
import { UsersTab } from "./users-tab"

const tabs = [
  { value: "documents", label: "Documents", icon: FileText, content: DocumentsTab },
  { value: "users", label: "Users", icon: Users, content: UsersTab },
  { value: "audit", label: "Audit log", icon: History, content: AuditTab },
  { value: "traces", label: "Query traces", icon: Route, content: TracesTab },
  { value: "analytics", label: "Analytics", icon: BarChart3, content: AnalyticsTab },
  { value: "settings", label: "Settings", icon: Settings, content: SettingsTab },
]

export function AdminPage() {
  const { role } = useDemo()

  // UI-only gate for the demo. The API enforces admin access (Phase 2/3).
  if (role !== "admin") {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center py-20 text-center">
        <ShieldAlert className="mb-4 size-10 text-muted-foreground" />
        <h2 className="text-xl font-semibold">Admins only</h2>
        <p className="mt-2 text-sm text-muted-foreground">You don&apos;t have access to this page. Ask an admin if you need it.</p>
        <Button asChild className="mt-6">
          <Link href="/search">Back to search</Link>
        </Button>
      </div>
    )
  }

  return (
    <Tabs defaultValue="documents" className="gap-6">
      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <TabsList className="w-max">
          {tabs.map(({ value, label, icon: Icon }) => (
            <TabsTrigger key={value} value={value}>
              <Icon /> {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      {tabs.map(({ value, content: Content }) => (
        <TabsContent key={value} value={value}>
          <Content />
        </TabsContent>
      ))}
    </Tabs>
  )
}
