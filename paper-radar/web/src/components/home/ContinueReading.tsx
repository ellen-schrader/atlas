import { Bookmark, Check } from "lucide-react";

import type { ReadingRow } from "@/hooks/useReadingList";
import { cn, formatRelative } from "@/lib/utils";
import { HeadingLink, SectionHeading } from "@/components/home/HomeSection";

/** "CONTINUE READING · Reading list · n →". Rendered apart from the card so the
 *  header grid can put it on the greeting's row (docs/dashboard.md §2.1). */
export function ContinueReadingHeading({
  count,
  onOpenList,
  className,
}: {
  count: number;
  className?: string;
  onOpenList: () => void;
}) {
  return (
    <SectionHeading
      className={className}
      title="Continue reading"
      right={<HeadingLink onClick={onOpenList}>Reading list · {count}</HeadingLink>}
    />
  );
}

/** The single next paper to read, or a one-line nudge when the list is empty.
 *  The empty state keeps the card's height so the header grid doesn't jump. */
export function ContinueReadingCard({
  next,
  compact,
  onOpen,
  onMarkRead,
}: {
  next: ReadingRow | undefined;
  /** false on phones: taller card, 44px tap target. */
  compact: boolean;
  onOpen: () => void;
  onMarkRead: () => void;
}) {
  const height = compact ? "h-[50px]" : "h-[60px]";
  if (!next) {
    return (
      <div className={cn("flex items-center px-1 text-meta text-muted", height)}>
        Nothing queued. Bookmark papers to build your list.
      </div>
    );
  }
  const p = next.papers;
  // updated_at is the last status write: the start for a paper in progress,
  // otherwise (usually) the save.
  const when = `${next.status === "reading" ? "started" : "saved"} ${formatRelative(next.updated_at)}`;
  const meta = [p?.venue, p?.year, when]
    .filter(Boolean)
    .join(" · ");
  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-3 rounded-card border border-border bg-surface px-2 transition hover:border-border-strong",
        height,
      )}
    >
      <span className="grid h-[34px] w-[34px] shrink-0 place-items-center rounded-lg border border-border bg-surface-2 text-muted">
        <Bookmark size={15} />
      </span>
      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 flex-1 rounded-control text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <span className="block truncate text-sm font-semibold">{p?.title ?? "A paper"}</span>
        <span className="mt-0.5 block truncate text-meta text-muted">{meta}</span>
      </button>
      <button
        type="button"
        onClick={onMarkRead}
        title="Mark as read"
        aria-label="Mark as read"
        className={cn(
          "grid shrink-0 place-items-center rounded-control border border-border text-muted transition hover:border-border-strong hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          compact ? "h-[30px] w-[30px]" : "h-11 w-11",
        )}
      >
        <Check size={15} />
      </button>
    </div>
  );
}
