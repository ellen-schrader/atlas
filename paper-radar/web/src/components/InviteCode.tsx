import { Check, Copy } from "lucide-react";

import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { cn } from "@/lib/utils";

/** A lab's join code with a copy-to-clipboard button. */
export function InviteCode({ code, className }: { code: string; className?: string }) {
  // clipboard unavailable — the code is still visible to copy manually
  const { copied, copy } = useCopyToClipboard();

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 rounded-control border border-border bg-surface-2 p-1 pl-3",
        className,
      )}
    >
      <code className="font-mono text-sm">{code}</code>
      <button
        type="button"
        onClick={() => copy(code)}
        aria-label="Copy join code"
        className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-muted transition hover:bg-surface-3 hover:text-fg"
      >
        {copied ? (
          <>
            <Check size={13} className="text-accent" /> Copied
          </>
        ) : (
          <>
            <Copy size={13} /> Copy
          </>
        )}
      </button>
    </div>
  );
}
