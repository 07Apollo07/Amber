import { cn } from "@/lib/utils"

export function AmberMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-7", className)}>
      <defs>
        <linearGradient id="amber-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="oklch(0.86 0.15 80)" />
          <stop offset="100%" stopColor="oklch(0.68 0.17 55)" />
        </linearGradient>
      </defs>
      <path d="M16 2.5 28 9.5v13L16 29.5 4 22.5v-13Z" fill="url(#amber-mark)" />
      <path d="M16 9.5 21.5 22h-2.7l-1.1-2.7h-3.4L13.2 22h-2.7Zm0 5.2-1.2 3h2.4Z" fill="oklch(0.2 0.04 60)" />
    </svg>
  )
}

export function AmberLogo() {
  return (
    <span className="flex items-center gap-2">
      <AmberMark />
      <span className="text-[15px] font-semibold tracking-[0.18em]">AMBER</span>
    </span>
  )
}
