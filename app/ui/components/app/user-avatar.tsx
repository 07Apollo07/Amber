import { User as UserIcon } from "lucide-react"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { initials } from "@/lib/format"
import type { SessionUser } from "@/lib/types"
import { cn } from "@/lib/utils"

export function UserAvatar({ user, className }: { user: SessionUser | null; className?: string }) {
  return (
    <Avatar className={className}>
      {user?.picture && <AvatarImage src={user.picture} alt="" referrerPolicy="no-referrer" />}
      <AvatarFallback className={cn("bg-primary/15 font-semibold text-primary")}>
        {user ? initials(user.name) : <UserIcon className="size-4" />}
      </AvatarFallback>
    </Avatar>
  )
}
