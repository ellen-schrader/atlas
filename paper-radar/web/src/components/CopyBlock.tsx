import { type ReactNode, useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

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
  const [copied, setCopied] = useState(false);
  // Copy-then-navigate is the expected flow here (you copy a command and leave for
  // the terminal), so the reset timer routinely outlives the component.
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked (insecure origin, denied permission) — the text is on
      // screen and selectable, so the user can still copy it by hand.
    }
  }

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
        onClick={copy}
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
