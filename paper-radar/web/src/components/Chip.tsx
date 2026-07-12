import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A small monospace tag/keyword chip. */
export function Chip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-chip border border-border bg-surface-2 px-2 py-0.5",
        "font-mono text-xs tracking-tight text-muted",
        className,
      )}
    >
      {children}
    </span>
  );
}
