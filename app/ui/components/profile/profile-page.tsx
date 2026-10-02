"use client"

import { CircleCheck, CircleX, ExternalLink, FolderOpen, History, LogOut, MessageSquare, Search, ShieldCheck, Trash2 } from "lucide-react"

import { FileIcon } from "@/components/app/file-icon"
import { SharingSummary } from "@/components/app/sharing-summary"
import { StatusBadge } from "@/components/app/status-badge"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { demoAction, useDemo } from "@/lib/demo"
import { initials } from "@/lib/format"
import { conversations, currentUser, documents, driveConnection, searchHistory } from "@/lib/mock-data"

import { DeleteDocumentDialog } from "./delete-document-dialog"
import { EditDocumentDialog } from "./edit-document-dialog"

function AccountCard() {
  const { role } = useDemo()
  return (
    <Card>
      <CardContent className="flex flex-col gap-5">
        <div className="flex items-center gap-4">
          <Avatar className="size-14">
            <AvatarFallback className="bg-primary/15 text-lg font-semibold text-primary">{initials(currentUser.name)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold">{currentUser.name}</p>
            <p className="truncate text-sm text-muted-foreground">{currentUser.email}</p>
            <Badge variant="outline" className="mt-1.5 capitalize">
              <ShieldCheck /> {role}
            </Badge>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => demoAction("Signed out")}>
            <LogOut /> Sign out
          </Button>
          <Button variant="ghost" className="text-muted-foreground" onClick={() => demoAction("Signed out of all sessions")}>
            Sign out of all devices
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function DriveCard() {
  const { driveConnected, setDriveConnected } = useDemo()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Google Drive
          {driveConnected ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-xs font-medium text-success">
              <CircleCheck className="size-3.5" /> Connected
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-md bg-destructive/15 px-1.5 py-0.5 text-xs font-medium text-destructive">
              <CircleX className="size-3.5" /> Not connected
            </span>
          )}
        </CardTitle>
        <CardDescription>Amber reads files you pick and saves your uploads to Drive.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {driveConnected && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Permissions</dt>
            <dd className="flex flex-wrap gap-1">
              {driveConnection.scopes.map((s) => (
                <code key={s} className="rounded bg-muted px-1.5 py-0.5 text-xs">
                  {s}
                </code>
              ))}
            </dd>
            <dt className="text-muted-foreground">Last sync</dt>
            <dd>{driveConnection.lastSync}</dd>
            <dt className="text-muted-foreground">Uploads folder</dt>
            <dd>
              <a
                href={driveConnection.uploadsFolderUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
              >
                <FolderOpen className="size-3.5" /> Amber Uploads <ExternalLink className="size-3" />
              </a>
            </dd>
          </dl>
        )}
        <div className="flex flex-wrap gap-2">
          {driveConnected ? (
            <>
              <Button variant="outline" onClick={() => demoAction("Reconnect Google Drive")}>
                Reconnect
              </Button>
              <Button
                variant="destructive"
                onClick={() => {
                  setDriveConnected(false)
                  demoAction("Drive disconnected", "Demo: uploads are now disabled until you reconnect.")
                }}
              >
                Disconnect
              </Button>
            </>
          ) : (
            <Button
              onClick={() => {
                setDriveConnected(true)
                demoAction("Google Drive connected")
              }}
            >
              Connect Google Drive
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function MyDocuments() {
  const mine = documents.filter((d) => d.owner === currentUser.email)
  return (
    <Card>
      <CardHeader>
        <CardTitle>My documents</CardTitle>
        <CardDescription>{mine.length} documents you added to Amber</CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        <ul className="divide-y divide-border/60">
          {mine.map((doc) => (
            <li key={doc.id} className="flex items-center gap-3 px-6 py-3">
              <FileIcon type={doc.fileType} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{doc.title}</p>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                  <SharingSummary sharing={doc.sharing} />
                  {doc.collection && <span className="text-xs text-muted-foreground">{doc.collection}</span>}
                  {doc.tags.map((t) => (
                    <span key={t} className="text-xs text-muted-foreground">
                      #{t}
                    </span>
                  ))}
                </div>
              </div>
              <div className="hidden sm:block">
                <StatusBadge status={doc.status} />
              </div>
              <div className="flex">
                {doc.driveUrl && (
                  <Button variant="ghost" size="icon-sm" asChild>
                    <a href={doc.driveUrl} target="_blank" rel="noopener noreferrer" aria-label={`Open ${doc.title} in Drive`}>
                      <ExternalLink />
                    </a>
                  </Button>
                )}
                <EditDocumentDialog doc={doc} />
                <DeleteDocumentDialog title={doc.title} inDrive={doc.driveUrl !== null} />
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function HistoryCard() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle className="flex items-center gap-2">
            <History className="size-4 text-muted-foreground" /> History
          </CardTitle>
          <CardDescription>Your chats and searches. Only you can see these.</CardDescription>
        </div>
        <Button variant="destructive" size="sm" onClick={() => demoAction("All history deleted")}>
          Delete all
        </Button>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="chats">
          <TabsList>
            <TabsTrigger value="chats">
              <MessageSquare /> Chats
            </TabsTrigger>
            <TabsTrigger value="searches">
              <Search /> Searches
            </TabsTrigger>
          </TabsList>
          <TabsContent value="chats">
            <ul className="mt-2 divide-y divide-border/60">
              {conversations.map((c) => (
                <li key={c.id} className="flex items-center gap-3 py-2.5">
                  <span className="min-w-0 flex-1 truncate text-sm">{c.title}</span>
                  <span className="text-xs text-muted-foreground">{c.updatedAt}</span>
                  <Button variant="ghost" size="icon-sm" aria-label={`Delete ${c.title}`} onClick={() => demoAction("Chat deleted")}>
                    <Trash2 />
                  </Button>
                </li>
              ))}
            </ul>
          </TabsContent>
          <TabsContent value="searches">
            <ul className="mt-2 divide-y divide-border/60">
              {searchHistory.map((h) => (
                <li key={h.id} className="flex items-center gap-3 py-2.5">
                  <span className="min-w-0 flex-1 truncate text-sm">{h.query}</span>
                  <span className="text-xs text-muted-foreground">{h.at}</span>
                  <Button variant="ghost" size="icon-sm" aria-label={`Delete "${h.query}"`} onClick={() => demoAction("Search deleted")}>
                    <Trash2 />
                  </Button>
                </li>
              ))}
            </ul>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

export function ProfilePage() {
  return (
    <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
      <div className="space-y-6">
        <AccountCard />
        <DriveCard />
      </div>
      <div className="min-w-0 space-y-6">
        <MyDocuments />
        <HistoryCard />
      </div>
    </div>
  )
}
