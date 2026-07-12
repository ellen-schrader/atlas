import { Avatar } from "@/components/Avatar";
import { Chip } from "@/components/Chip";
import { Cover } from "@/components/Cover";
import { EngagementSummary } from "@/components/EngagementSummary";
import { SourceLabel } from "@/components/SourceLabel";
import type { PaperPost } from "@/lib/types";
import { cn, formatAuthors, formatDate } from "@/lib/utils";

/** A paper in the lab's collection: cover, source, title, authors, tags, and a
 *  footer with engagement + who posted. Opens the detail view on click. */
export function PaperCard({
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
  const tags = post.tags.length ? post.tags : p.tags;
  const shown = tags.slice(0, 3);
  const extra = tags.length - shown.length;

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={cn(
        "flex cursor-pointer flex-col overflow-hidden rounded-card border border-border bg-surface shadow-sm transition",
        "hover:-translate-y-0.5 hover:border-border-strong",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
      )}
    >
      <div className="h-[132px] w-full">
        <Cover seed={p.id} />
      </div>
      <div className="flex flex-col gap-2.5 p-4">
        <SourceLabel venue={p.venue} year={p.year} />
        <h3 className="text-card font-semibold tracking-snug text-fg">{p.title ?? p.url}</h3>
        {p.authors.length > 0 && <div className="text-meta text-muted">{formatAuthors(p.authors)}</div>}
        {shown.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {shown.map((t) => (
              <Chip key={t}>{t}</Chip>
            ))}
            {extra > 0 && <Chip className="text-faint">+{extra}</Chip>}
          </div>
        )}
        <div className="mt-1 flex items-center justify-between gap-3 border-t border-border pt-3">
          <EngagementSummary reactions={reactions} comments={comments} />
          <span className="text-meta inline-flex items-center gap-2 text-muted">
            {post.posted_by_label && <Avatar name={post.posted_by_label} size={20} />}
            <span className="tabular-nums">{formatDate(post.posted_at)}</span>
          </span>
        </div>
      </div>
    </article>
  );
}
