import { Avatar } from "@/components/Avatar";
import { BookmarkButton } from "@/components/BookmarkButton";
import { Chip } from "@/components/Chip";
import { Cover } from "@/components/Cover";
import { EngagementSummary } from "@/components/EngagementSummary";
import { SelectCheckbox } from "@/components/ExportBar";
import { SourceLabel } from "@/components/SourceLabel";
import type { PaperPost } from "@/lib/types";
import { cn, formatAuthors, formatDate, formatRelative } from "@/lib/utils";

/** A paper in the lab's collection: source, title, authors, tags, and a footer with
 *  engagement + who posted. Opens the detail view on click.
 *
 *  The generative cover used to be a 132px block — nearly half the card, and it
 *  encodes nothing but the paper's id. It's kept as a spine, so the lab's palette
 *  still runs down the grid, but the words get the space. */
export function PaperCard({
  post,
  reactions = 0,
  comments = 0,
  onOpen,
  teamId,
  userId,
  bookmarked = false,
  read,
  selecting = false,
  selected = false,
  onToggleSelect,
}: {
  post: PaperPost;
  reactions?: number;
  comments?: number;
  onOpen: () => void;
  teamId?: string;
  userId?: string;
  bookmarked?: boolean;
  /** Read by *you*. Shown as a dot, so an unread paper is findable at a glance.
   *  Leave undefined where read state isn't loaded (the dashboard) — an "unread"
   *  dot on every card would be a claim we haven't checked. */
  read?: boolean;
  /** Multi-select mode: the whole card toggles selection instead of opening. */
  selecting?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
}) {
  const p = post.papers;
  const posterName = post.posted_by_label ?? post.poster?.display_name ?? null;
  const tags = post.tags.length ? post.tags : p.tags;
  const shown = tags.slice(0, 3);
  const extra = tags.length - shown.length;

  const activate = selecting ? onToggleSelect ?? onOpen : onOpen;

  return (
    <article
      role="button"
      tabIndex={0}
      aria-pressed={selecting ? selected : undefined}
      onClick={activate}
      onKeyDown={(e) => {
        // Only when the card itself has focus: keydown bubbles, so without this an
        // Enter/Space on the nested checkbox or bookmark would double-fire (its own
        // click plus this handler). Same guard PaperListRow uses.
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          activate();
        }
      }}
      className={cn(
        "relative flex h-full cursor-pointer flex-col overflow-hidden rounded-card border bg-surface shadow-sm transition",
        "hover:-translate-y-0.5 hover:border-border-strong",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        selected ? "border-accent ring-1 ring-accent" : "border-border",
      )}
    >
      {selecting && (
        <div className="absolute left-2.5 top-2.5 z-10">
          <SelectCheckbox
            checked={selected}
            onChange={() => (onToggleSelect ?? onOpen)()}
            className="shadow-sm"
          />
        </div>
      )}
      {/* The cover is a 600×340 canvas squashed into a 6px strip, so its fluorophore
          blobs average out into a far more saturated band than they read as at full
          size. Knock it back, or every card in the grid shouts a different colour. */}
      <div className="relative h-1.5 w-full shrink-0 opacity-[0.35]">
        <Cover seed={p.id} />
      </div>

      <div className="flex flex-1 flex-col gap-2.5 p-4">
        <div className="flex items-start justify-between gap-2">
          <SourceLabel venue={p.venue} year={p.year} />
          {read === false && (
            <span
              aria-label="Unread"
              title="Unread"
              className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
            />
          )}
        </div>

        <h3 className="text-card font-semibold tracking-snug text-fg">{p.title ?? p.url}</h3>

        {p.authors.length > 0 && (
          <div className="text-meta text-muted">{formatAuthors(p.authors)}</div>
        )}

        {shown.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {shown.map((t) => (
              <Chip key={t}>{t}</Chip>
            ))}
            {extra > 0 && <Chip className="text-faint">+{extra}</Chip>}
          </div>
        )}

        <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-3">
          <EngagementSummary reactions={reactions} comments={comments} />
          <span className="text-meta inline-flex items-center gap-2 text-muted">
            {posterName && <Avatar name={posterName} size={20} />}
            {/* Relative reads better in a feed, and the exact date is a hover away. */}
            <span className="tabular-nums" title={formatDate(post.posted_at)}>
              {formatRelative(post.posted_at)}
            </span>
            {/* With the cover gone there's nothing to overlay, so the bookmark lives
                in the footer — where it's always visible, not just on a hover. */}
            {teamId && userId && (
              <span onClick={(e) => e.stopPropagation()}>
                <BookmarkButton
                  paperId={p.id}
                  teamId={teamId}
                  userId={userId}
                  bookmarked={bookmarked}
                  className="-mr-1 text-faint hover:text-accent aria-pressed:text-accent"
                />
              </span>
            )}
          </span>
        </div>
      </div>
    </article>
  );
}
