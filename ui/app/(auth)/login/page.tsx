import type { Metadata } from "next"
import { redirect } from "next/navigation"
import { CircleAlert, FileSearch, FolderUp, Lock, ShieldCheck } from "lucide-react"

import { AmberMark } from "@/components/app/amber-logo"
import { GoogleSignInButton } from "@/components/app/google-sign-in-button"
import { safeReturnTo } from "@/lib/auth-paths"
import { getSession } from "@/lib/session"

export const metadata: Metadata = { title: "Sign in" }

const permissions = [
  {
    icon: FileSearch,
    title: "Browse and read Drive files",
    body: "Browse your Google Drive files to select and index them in Amber.",
  },
  {
    icon: FolderUp,
    title: "Save your uploads to Drive",
    body: "Files you upload go into an “Amber Uploads” folder in your Drive.",
  },
  {
    icon: Lock,
    title: "Respect existing sharing",
    body: "Answers only use documents you already have access to.",
  },
]

// Codes come from the API's /login?error=… redirects (amber/api/auth.py).
const errors: Record<string, string> = {
  state: "Your sign-in attempt expired. Please try again.",
  denied: "Sign-in was cancelled on the Google screen.",
  email_not_verified: "Your Google account's email address isn't verified.",
  deactivated: "Your Amber account has been deactivated. Contact an admin.",
  rate_limited: "Too many sign-in attempts. Please wait a minute and try again.",
  firebase_signin: "Amber couldn't complete sign-in with Firebase. Please try again, or contact an admin if it keeps happening.",
  firebase_session: "Amber couldn't start your session. Please try again, or contact an admin if it keeps happening.",
}
const genericError = "Something went wrong signing you in. Please try again."

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams
  const returnTo = safeReturnTo(typeof params.return_to === "string" ? params.return_to : null)
  const errorCode = typeof params.error === "string" ? params.error : null

  const session = await getSession()
  if (session.user) redirect(returnTo)

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <AmberMark className="mb-5 size-12 drop-shadow-[0_0_24px_oklch(0.8_0.155_72/35%)]" />
          <h1 className="text-3xl font-semibold tracking-tight">Welcome to Amber</h1>
          <p className="mt-2 text-muted-foreground">
            Ask questions across your company&apos;s documents and get answers with sources.
          </p>
        </div>

        <div className="rounded-2xl border bg-card/80 p-6 shadow-2xl shadow-black/30 backdrop-blur">
          {errorCode && (
            <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm">
              <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
              <span>{errors[errorCode] ?? genericError}</span>
            </div>
          )}

          <GoogleSignInButton returnTo={returnTo} />

          <div className="mt-6">
            <p className="mb-3 flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
              <ShieldCheck className="size-3.5 text-primary" />
              Google will ask you to allow Amber to
            </p>
            <ul className="space-y-3">
              {permissions.map(({ icon: Icon, title, body }) => (
                <li key={title} className="flex gap-3">
                  <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="size-4" />
                  </span>
                  <span>
                    <span className="block text-sm font-medium">{title}</span>
                    <span className="block text-sm text-muted-foreground">{body}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Amber requests the <code className="rounded bg-muted px-1 py-0.5">drive.file</code> scope, so it can only open
          files you pick or that it saved for you. You can disconnect Drive anytime from your profile.
        </p>
      </div>
    </main>
  )
}
