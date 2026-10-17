import { ExternalLink } from "lucide-react";

import { type PreprintLink, preprintHref } from "@/lib/preprint";
import { cn, safeHref } from "@/lib/utils";

/** "PREPRINT", next to the venue of a paper that has not been published (yet). */
export function PreprintBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-chip border border-current px-1.5 py-px",
        "text-[10px] font-semibold uppercase leading-none tracking-wide opacity-80",
        className,
      )}
    >
      Preprint
    </span>
  );
}

/** A link to a published paper's preprint, for whatever the journal version cut.
 *  Stops the click so a card that opens on click doesn't open as well. */
export function PreprintVersionLink({
  preprint,
  className,
}: {
  preprint: PreprintLink;
  className?: string;
}) {
  const href = safeHref(preprintHref(preprint));
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      title="The preprint version of this paper"
      className={cn(
        "inline-flex items-center gap-1 text-xs text-muted underline-offset-2 hover:text-fg hover:underline",
        className,
      )}
    >
      {preprint.venue ? `${preprint.venue} preprint` : "Preprint"}
      <ExternalLink size={11} aria-hidden />
    </a>
  );
}
