"use client"

import { useState } from "react"
import { Building2, Lock, UsersRound, X } from "lucide-react"

import { Input } from "@/components/ui/input"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import type { Sharing } from "@/lib/types"
import { cn } from "@/lib/utils"

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function SharingSelector({
  value,
  onChange,
  domain,
}: {
  value: Sharing
  onChange: (next: Sharing) => void
  /** The user's Google Workspace domain; null for consumer accounts. */
  domain: string | null
}) {
  const [emailDraft, setEmailDraft] = useState("")
  const [emailError, setEmailError] = useState<string | null>(null)
  const emails = value.kind === "people" ? value.emails : []

  function addEmail() {
    const email = emailDraft.trim().toLowerCase()
    if (!email) return
    if (!EMAIL.test(email)) {
      setEmailError("Enter a valid email address")
      return
    }
    if (!emails.includes(email)) onChange({ kind: "people", emails: [...emails, email] })
    setEmailDraft("")
    setEmailError(null)
  }

  const options = [
    { kind: "private" as const, icon: Lock, title: "Private", body: "Only you" },
    { kind: "people" as const, icon: UsersRound, title: "Specific people", body: "People you add by email" },
    ...(domain ? [{ kind: "domain" as const, icon: Building2, title: `Everyone at @${domain}`, body: "Anyone in your organization" }] : []),
  ]

  return (
    <div className="space-y-3">
      <RadioGroup
        value={value.kind}
        onValueChange={(kind) => {
          if (kind === "private") onChange({ kind: "private" })
          if (kind === "people") onChange({ kind: "people", emails })
          if (kind === "domain" && domain) onChange({ kind: "domain", domain })
        }}
        className="gap-2"
        aria-label="Who can access"
      >
        {options.map(({ kind, icon: Icon, title, body }) => (
          <label
            key={kind}
            htmlFor={`share-${kind}`}
            className={cn(
              "flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition-colors hover:bg-muted/40",
              value.kind === kind && "border-primary/50 bg-primary/5",
            )}
          >
            <RadioGroupItem id={`share-${kind}`} value={kind} />
            <Icon className={cn("size-4 text-muted-foreground", value.kind === kind && "text-primary")} />
            <span>
              <span className="block text-sm font-medium">{title}</span>
              <span className="block text-xs text-muted-foreground">{body}</span>
            </span>
          </label>
        ))}
      </RadioGroup>

      {value.kind === "people" && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {emails.map((email) => (
              <span key={email} className="inline-flex items-center gap-1 rounded-full bg-muted py-0.5 pr-1 pl-2.5 text-xs">
                {email}
                <button
                  type="button"
                  aria-label={`Remove ${email}`}
                  onClick={() => onChange({ kind: "people", emails: emails.filter((e) => e !== email) })}
                  className="rounded-full p-0.5 hover:bg-background"
                >
                  <X className="size-3" />
                </button>
              </span>
            ))}
          </div>
          <Input
            type="email"
            value={emailDraft}
            onChange={(event) => {
              setEmailDraft(event.target.value)
              setEmailError(null)
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === ",") {
                event.preventDefault()
                addEmail()
              }
            }}
            onBlur={addEmail}
            placeholder="name@company.com, press Enter to add"
            aria-label="Add person by email"
            aria-invalid={emailError ? true : undefined}
          />
          {emailError && <p className="text-xs text-destructive">{emailError}</p>}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        This sharing is also applied to the file in your Google Drive. People you add get view access and no email
        notification.
      </p>
    </div>
  )
}
