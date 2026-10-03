"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { CircleCheck, CircleX, ExternalLink, FileText, History, LogOut, MessageSquare, Search, ShieldCheck, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { EmptyState } from "@/components/app/empty-state"
import { FileIcon } from "@/components/app/file-icon"
import { SharingSummary } from "@/components/app/sharing-summary"
import { useSignOut } from "@/components/app/sign-out"
import { StatusBadge } from "@/components/app/status-badge"
import { UserAvatar } from "@/components/app/user-avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiPost } from "@/lib/api"
import { googleSignInUrl } from "@/lib/auth-paths"
import { demoAction } from "@/lib/demo"
import { useSession } from "@/lib/session-context"
import type { AmberDocument, Conversation, SearchHistoryItem } from "@/lib/types"

import { DeleteDocumentDialog } from "./delete-document-dialog"
import { EditDocumentDialog } from "./edit-document-dialog"

// Loaded from the API once it exists.
const myDocuments: AmberDocument[] = []
const conversations: Conversation[] = []
const searchHistory: SearchHistoryItem[] = []

function AccountCard() {
  const user = useSession()
  const { signOut, pending } = useSignOut()
  return (
    <Card>
      <CardContent className="flex flex-col gap-5">
        <div className="flex items-center gap-4">
          <UserAvatar user={user} className="size-14 text-lg" />
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold">{user.name}</p>
            <p className="truncate text-sm text-muted-foreground">{user.email}</p>
            <Badge variant="outline" className="mt-1.5 capitalize">
              <ShieldCheck /> {user.role}
            </Badge>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={pending} onClick={() => signOut()}>
            <LogOut /> Sign out
          </Button>
          <Button variant="ghost" className="text-muted-foreground" disabled={pending} onClick={() => signOut(true)}>
            Sign out of all devices
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

/** Google scope URLs → the short names people recognise. */
function scopeLabel(scope: string): string {
  return scope.replace("https://www.googleapis.com/auth/", "").replace(/^userinfo\./, "")
}

function DisconnectDriveButton() {
  const router = useRouter()
  const [pending, setPending] = useState(false)
  const [open, setOpen] = useState(false)

  async function disconnect() {
    setPending(true)
    try {
      const res = await apiPost("/api/auth/google/disconnect")
      const { revoked_at_google } = (await res.json()) as { revoked_at_google: boolean }
      setOpen(false)
      if (revoked_at_google) {
        toast.success("Google Drive disconnected")
      } else {
        // Amber deleted its copy but couldn't confirm Google removed the grant.
        toast.warning("Removed from Amber", {
          description: "To be sure, also remove Amber under Third-party access at myaccount.google.com/connections.",
          duration: 15000,
        })
      }
      router.refresh()
    } catch (err) {
      toast.error("Couldn't disconnect Google Drive", {
        description: err instanceof Error ? err.message : "Please try again.",
      })
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="destructive">Disconnect</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Disconnect Google Drive?</DialogTitle>
          <DialogDescription>
            Amber will lose access to your Drive. You won&apos;t be able to upload files or add Drive files until
            you reconnect. Files already in your Drive stay there.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button variant="destructive" disabled={pending} onClick={disconnect}>
            {pending ? "Disconnecting…" : "Disconnect"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DriveCard() {
  const { drive } = useSession()
  const reconnectUrl = googleSignInUrl("/profile", { reconnect: true })
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Google Drive
          {drive.connected ? (
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
        {drive.scopes.length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Permissions</dt>
            <dd className="flex flex-wrap gap-1">
              {drive.scopes.map((s) => (
                <code key={s} className="rounded bg-muted px-1.5 py-0.5 text-xs" title={s}>
                  {scopeLabel(s)}
                </code>
              ))}
            </dd>
          </dl>
        )}
        {!drive.connected && (
          <p className="text-sm text-muted-foreground">
            Connect Drive to upload files and add documents from your Drive.
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {drive.connected ? (
            <>
              <Button variant="outline" asChild>
                <a href={reconnectUrl}>Reconnect</a>
              </Button>
              <DisconnectDriveButton />
            </>
          ) : (
            <Button asChild>
              <a href={reconnectUrl}>Connect Google Drive</a>
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
