"use client"

import { BarChart3, FileText, History, Route, Settings, Users } from "lucide-react"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

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

/** Rendered only for admins (checked server-side in app/(app)/admin/page.tsx). */
export function AdminPage() {
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
