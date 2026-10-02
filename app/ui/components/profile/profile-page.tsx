"use client"

import Link from "next/link"
import { CircleCheck, CircleX, ExternalLink, FileText, History, LogIn, LogOut, MessageSquare, Search, ShieldCheck, Trash2, User as UserIcon } from "lucide-react"

import { EmptyState } from "@/components/app/empty-state"
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
import type { AmberDocument, Conversation, SearchHistoryItem } from "@/lib/types"

import { DeleteDocumentDialog } from "./delete-document-dialog"
import { EditDocumentDialog } from "./edit-document-dialog"

/** Scopes Amber requests at sign-in (see PLAN.md, Phase 2). */
const DRIVE_SCOPES = ["openid", "email", "profile", "drive.file"]

// Loaded from the API once it exists.
const myDocuments: AmberDocument[] = []
const conversations: Conversation[] = []
const searchHistory: SearchHistoryItem[] = []

function AccountCard() {
  const { user, role } = useDemo()
  return (
    <Card>
      <CardContent className="flex flex-col gap-5">
        <div className="flex items-center gap-4">
          <Avatar className="size-14">
            <AvatarFallback className="bg-primary/15 text-lg font-semibold text-primary">
              {user ? initials(user.name) : <UserIcon className="size-6" />}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold">{user?.name ?? "Not signed in"}</p>
            {user && <p className="truncate text-sm text-muted-foreground">{user.email}</p>}
            <Badge variant="outline" className="mt-1.5 capitalize">
              <ShieldCheck /> {role}
            </Badge>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {user ? (
            <>
              <Button variant="outline" onClick={() => demoAction("Signed out")}>
                <LogOut /> Sign out
              </Button>
              <Button variant="ghost" className="text-muted-foreground" onClick={() => demoAction("Signed out of all sessions")}>
                Sign out of all devices
              </Button>
            </>
          ) : (
            <Button asChild>
              <Link href="/login">
                <LogIn /> Sign in
              </Link>
            </Button>
          )}
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
        <CardDescription>Amber reads files you pick and saves your uploads to an Amber Uploads folder in Drive.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {driveConnected && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Permissions</dt>
            <dd className="flex flex-wrap gap-1">
              {DRIVE_SCOPES.map((s) => (
                <code key={s} className="rounded bg-muted px-1.5 py-0.5 text-xs">
                  {s}
                </code>
              ))}
            </dd>
            <dt className="text-muted-foreground">Last sync</dt>
            <dd className="text-muted-foreground">Not synced yet</dd>
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
  return (
    <Card>
      <CardHeader>
        <CardTitle>My documents</CardTitle>
        <CardDescription>Documents you added to Amber</CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        {myDocuments.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No documents yet"
            description="Upload files or pick them from Google Drive to search them with Amber."
            action={
              <Button asChild variant="outline">
                <Link href="/upload">Go to Upload</Link>
              </Button>
            }
          />
        ) : (
          <ul className="divide-y divide-border/60">
            {myDocuments.map((doc) => (
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
        )}
      </CardContent>
    </Card>
  )
}

function HistoryList({ items, empty }: { items: { id: string; label: string; at: string }[]; empty: string }) {
  if (items.length === 0) return <EmptyState icon={History} title={empty} className="py-8" />
  return (
    <ul className="mt-2 divide-y divide-border/60">
      {items.map((item) => (
        <li key={item.id} className="flex items-center gap-3 py-2.5">
          <span className="min-w-0 flex-1 truncate text-sm">{item.label}</span>
          <span className="text-xs text-muted-foreground">{item.at}</span>
          <Button variant="ghost" size="icon-sm" aria-label={`Delete ${item.label}`} onClick={() => demoAction("Deleted")}>
            <Trash2 />
          </Button>
        </li>
      ))}
    </ul>
  )
}

function HistoryCard() {
  const hasHistory = conversations.length > 0 || searchHistory.length > 0
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle className="flex items-center gap-2">
            <History className="size-4 text-muted-foreground" /> History
          </CardTitle>
          <CardDescription>Your chats and searches. Only you can see these.</CardDescription>
        </div>
        <Button variant="destructive" size="sm" disabled={!hasHistory} onClick={() => demoAction("All history deleted")}>
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
            <HistoryList items={conversations.map((c) => ({ id: c.id, label: c.title, at: c.updatedAt }))} empty="No chats yet" />
          </TabsContent>
          <TabsContent value="searches">
            <HistoryList items={searchHistory.map((h) => ({ id: h.id, label: h.query, at: h.at }))} empty="No searches yet" />
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
