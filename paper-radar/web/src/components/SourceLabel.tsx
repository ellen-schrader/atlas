import { PreprintBadge } from "@/components/PreprintBadge";
import { isPreprintVenue } from "@/lib/preprint";
import { cn } from "@/lib/utils";

/** Uppercase source eyebrow, e.g. "NATURE · 2023", or "BIORXIV · 2025 [PREPRINT]".
 *  Renders nothing if empty. */
export function SourceLabel({
  venue,
  year,
  className,
}: {
  venue?: string | null;
  year?: number | null;
  className?: string;
}) {
  const parts = [venue, year].filter(Boolean);
  if (parts.length === 0) return null;
  return (
    <span
      className={cn(
        "text-eyebrow font-semibold uppercase tracking-eyebrow text-muted tabular-nums",
        className,
      )}
    >
      {parts.join(" · ")}
      {isPreprintVenue(venue) && <PreprintBadge className="ml-1.5 align-[1px]" />}
    </span>
  );
}
