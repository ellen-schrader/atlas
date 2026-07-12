import { Avatar } from "@/components/Avatar";
import { EngagementSummary } from "@/components/EngagementSummary";
import type { PaperPost } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

/** Compact one-line paper row for dense lists (e.g. "Recently posted"). An unread
 *  dot + full-strength title distinguishes new papers; read ones dim. Metadata is
 *  a quiet venue · year · tags line; reaction + comment counts sit on the right
 *  (always shown, including zero). No thumbnail — it's for the card view. */
export function PaperListRow({
  post,
  reactions = 0,
  comments = 0,
  read = false,
  onOpen,
}: {
  post: PaperPost;
  reactions?: number;
  comments?: number;
  read?: boolean;
  onOpen: () => void;
}) {
  const p = post.papers;
  const posterName = post.posted_by_label ?? post.poster?.display_name ?? null;
  const tags = (post.tags.length ? post.tags : p.tags).slice(0, 2);

  return (
    <button
      onClick={onOpen}
      className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-surface-2"
    >
      <span
        aria-label={read ? undefined : "Unread"}
        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", read ? "bg-transparent" : "bg-accent")}
      />
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block truncate text-sm",
            read ? "font-medium text-muted" : "font-semibold text-fg",
          )}
        >
          {p.title ?? p.url}
        </span>
        <span className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted">
          {p.venue && <span className="font-semibold uppercase tracking-wide">{p.venue}</span>}
          {p.year != null && <span>· {p.year}</span>}
          {tags.length > 0 && <span className="truncate text-faint">· {tags.join(", ")}</span>}
        </span>
      </span>
      <EngagementSummary reactions={reactions} comments={comments} className="hidden sm:flex" />
      <span className="inline-flex shrink-0 items-center gap-2 text-xs text-muted">
        {posterName && <Avatar name={posterName} size={20} />}
        <span className="whitespace-nowrap tabular-nums">{formatDate(post.posted_at)}</span>
      </span>
    </button>
  );
}
