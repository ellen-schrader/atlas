import { type ReactNode } from "react";
import { Check, Copy } from "lucide-react";

import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { cn } from "@/lib/utils";

/**
 * A copyable snippet. `value` is what lands on the clipboard; `children` is what's
 * shown, so a block can highlight parts of itself without those spans ending up in
 * the paste. (InviteCode does the same for a single short code; this one is for
 * multi-line config where the two differ.)
 */
export function CopyBlock({
  value,
  children,
  label = "Copy",
  className,
}: {
  value: string;
  children?: ReactNode;
  label?: string;
  className?: string;
}) {
  // Copy-then-navigate is the expected flow here (you copy a command and leave for
  // the terminal); the hook clears its reset timer on unmount. When the clipboard is
  // blocked the text is still on screen and selectable, so a failed copy is a no-op.
  const { copied, copy } = useCopyToClipboard();

  return (
    <div
      className={cn(
        "relative rounded-control border border-border bg-bg font-mono text-xs",
        className,
      )}
    >
      <pre className="overflow-x-auto p-3 pr-20 leading-relaxed">
        <code>{children ?? value}</code>
      </pre>
      <button
        type="button"
        onClick={() => copy(value)}
        aria-label={copied ? "Copied" : label}
        className="absolute right-2 top-2 inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1 font-sans text-xs font-medium text-muted transition hover:border-accent hover:text-accent"
      >
        {copied ? (
          <>
            <Check size={12} className="text-accent" /> Copied
          </>
        ) : (
          <>
            <Copy size={12} /> {label}
          </>
        )}
      </button>
    </div>
  );
}
