import { Avatar } from "@/components/Avatar";
import { Cover } from "@/components/Cover";
import { EngagementSummary } from "@/components/EngagementSummary";
import type { PaperPost } from "@/lib/types";
import { formatDate } from "@/lib/utils";

/** Compact one-line paper row for dense lists (e.g. "Recently posted"). */
export function PaperListRow({
  post,
  reactions = 0,
  comments = 0,
  onOpen,
}: {
  post: PaperPost;
  reactions?: number;
  comments?: number;
  onOpen: () => void;
}) {
  const p = post.papers;
  const posterName = post.posted_by_label ?? post.poster?.display_name ?? null;
  const sub = [p.venue, p.year].filter(Boolean).join(" · ");
  const lead = p.authors[0] ? `${sub ? sub + " · " : ""}${p.authors[0]}${p.authors.length > 1 ? " et al." : ""}` : sub;

  return (
    <button
      onClick={onOpen}
      className="flex w-full items-center gap-3.5 px-4 py-3 text-left transition hover:bg-surface-2"
    >
      <span className="h-9 w-14 shrink-0 overflow-hidden rounded-md border border-border">
        <Cover seed={p.id} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{p.title ?? p.url}</span>
        <span className="mt-0.5 block truncate text-xs text-muted">{lead}</span>
      </span>
      <EngagementSummary reactions={reactions} comments={comments} className="hidden sm:flex" />
      <span className="inline-flex shrink-0 items-center gap-2 text-xs text-muted">
        {posterName && <Avatar name={posterName} size={20} />}
        <span className="whitespace-nowrap tabular-nums">{formatDate(post.posted_at)}</span>
      </span>
    </button>
  );
}
