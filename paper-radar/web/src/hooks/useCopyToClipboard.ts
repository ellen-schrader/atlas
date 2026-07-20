import { useCallback, useEffect, useRef, useState } from "react";

/** Copy-to-clipboard with a self-resetting "copied" flag — the pattern shared by
 *  CopyBlock, InviteCode, and the export popover. `copy` resolves to `false` when
 *  the clipboard is unavailable (insecure origin / denied permission) so the caller
 *  can fall back (e.g. to a download); the on-screen text stays selectable either way.
 *
 *  The reset timer routinely outlives the component (you copy, then navigate away),
 *  so it's cleared on unmount. */
export function useCopyToClipboard(resetMs = 1500) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = useCallback(
    async (text: string): Promise<boolean> => {
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), resetMs);
        return true;
      } catch {
        return false;
      }
    },
    [resetMs],
  );

  return { copied, copy };
}
