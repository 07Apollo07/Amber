export function CitationChip({ n, onClick }: { n: number; onClick: (n: number) => void }) {
  return (
    <button
      type="button"
      onClick={() => onClick(n)}
      aria-label={`Open source ${n}`}
      className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-md bg-primary/15 px-1 align-middle text-[11px] font-semibold text-primary transition-colors hover:bg-primary hover:text-primary-foreground"
    >
      {n}
    </button>
  )
}
