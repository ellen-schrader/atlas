import { Fragment, useState } from "react";
import { MessageSquare } from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { BookmarkButton } from "@/components/BookmarkButton";
import { HeadingLink, SectionHeading, Segmented, TopicDot } from "@/components/home/HomeSection";
import type { Counts } from "@/hooks/useEngagementCounts";
import type { PaperPost } from "@/lib/types";
import { cn, formatAgo, formatDate } from "@/lib/utils";

type FeedFilter = "all" | "unread" | "comments";

const ROWS = 8;
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

/** The lab's newest posts, grouped by day, with All / Unread / With comments.
 *  The card stretches (flex-1) so it ends level with the right rail. */
export function LabFeed({
  posts,
  loading,
  counts,
  readIds,
  bookmarkedIds,
  teamId,
  userId,
  mobile,
  onOpen,
  onBrowseAll,
}: {
  posts: PaperPost[];
  loading: boolean;
  counts: Record<string, Counts> | undefined;
  readIds: Set<string> | undefined;
  bookmarkedIds: Set<string>;
  teamId: string;
  userId: string;
  mobile: boolean;
  onOpen: (paperId: string) => void;
  onBrowseAll: () => void;
}) {
  const [filter, setFilter] = useState<FeedFilter>("all");
  const isUnread = (p: PaperPost) => !readIds?.has(p.papers.id);
  const hasComments = (p: PaperPost) => (counts?.[p.papers.id]?.comments ?? 0) > 0;
  // "Unread n" counts the loaded window (the newest page of posts), which is
  // what the filter can show.
  const unreadCount = readIds ? posts.filter(isUnread).length : 0;

  const filtered = posts.filter((p) =>
    filter === "unread" ? isUnread(p) : filter === "comments" ? hasComments(p) : true,
  );
  const shown = filtered.slice(0, ROWS);
  const weekAgo = Date.now() - WEEK_MS;
  const moreThisWeek = filtered
    .slice(ROWS)
    .filter((p) => new Date(p.posted_at).getTime() >= weekAgo).length;

  const options: { value: FeedFilter; label: string }[] = [
    { value: "all", label: "All" },
    { value: "unread", label: unreadCount ? `Unread ${unreadCount}` : "Unread" },
  ];
  // Phones keep All and Unread only (docs/dashboard.md §2.3).
  if (!mobile) options.push({ value: "comments", label: "With comments" });

  let lastGroup = "";

  return (
    <section className="flex min-w-0 flex-1 flex-col">
      <SectionHeading
        title="Lab feed"
        controls={
          <Segmented value={filter} options={options} onChange={setFilter} label="Filter the lab feed" />
        }
        right={!mobile && <HeadingLink onClick={onBrowseAll}>Browse all</HeadingLink>}
      />
      <div className="flex flex-1 flex-col overflow-hidden rounded-card border border-border bg-surface">
        {loading ? (
          <FeedSkeleton />
        ) : shown.length === 0 ? (
          <div className="grid flex-1 place-items-center px-6 py-12 text-center text-sm text-muted">
            {filter === "unread"
              ? "You’re all caught up."
              : filter === "comments"
                ? "No discussions on recent papers yet."
                : "No papers in your lab yet. Paste a DOI above to add the first one."}
          </div>
        ) : (
          <div role="list">
            {shown.map((post) => {
              const group = dayLabel(post.posted_at);
              const header = group !== lastGroup;
              lastGroup = group;
              return (
                <Fragment key={post.id}>
                  {header && (
                    <div className="border-b border-border bg-bg/60 px-[18px] py-2 text-[10.5px] font-semibold uppercase tracking-eyebrow text-faint">
                      {group}
                    </div>
                  )}
                  <FeedRow
                    post={post}
                    unread={readIds ? isUnread(post) : false}
                    comments={counts?.[post.papers.id]?.comments ?? 0}
                    bookmarked={bookmarkedIds.has(post.papers.id)}
                    teamId={teamId}
                    userId={userId}
                    mobile={mobile}
                    onOpen={() => onOpen(post.papers.id)}
                  />
                </Fragment>
              );
            })}
          </div>
        )}
        {!loading && (
          <button
            type="button"
            onClick={onBrowseAll}
            className="mt-auto border-t border-border px-4 py-3 text-sm font-medium text-muted transition hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
          >
            {moreThisWeek > 0 ? `Show ${moreThisWeek} more from this week` : "Browse all papers"}
          </button>
        )}
      </div>
    </section>
  );
}

function FeedRow({
  post,
  unread,
  comments,
  bookmarked,
  teamId,
  userId,
  mobile,
  onOpen,
}: {
  post: PaperPost;
  unread: boolean;
  comments: number;
  bookmarked: boolean;
  teamId: string;
  userId: string;
  mobile: boolean;
  onOpen: () => void;
}) {
  const p = post.papers;
  const poster = post.posted_by_label ?? post.poster?.display_name ?? null;
  const tags = (post.tags.length ? post.tags : p.tags).slice(0, 2);

  return (
    <div role="listitem" className="border-b border-border last:border-b-0">
      {/* role="button", not <button>: the bookmark inside is itself a button. */}
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onOpen();
          }
        }}
        className="grid min-h-11 cursor-pointer grid-cols-[6px_minmax(0,1fr)_auto] items-center gap-x-3.5 px-[18px] py-3 transition hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
      >
        <span
          aria-label={unread ? "Unread" : undefined}
          title={unread ? "Unread" : undefined}
          className={cn("h-1.5 w-1.5 rounded-full", unread ? "bg-accent" : "bg-transparent")}
        />
        <div className="min-w-0">
          <div className={cn("text-sm font-semibold", mobile ? "line-clamp-2" : "truncate")}>
            {p.title ?? p.url}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5 text-meta text-muted">
            <TopicDot />
            {p.venue && (
              <span className="max-w-[45%] shrink-0 truncate font-semibold uppercase tracking-wide">
                {p.venue}
              </span>
            )}
            {p.year != null && <span className="shrink-0">· {p.year}</span>}
            {mobile ? (
              <>
                {poster && <span className="truncate">· {poster.split(/[\s@]/)[0]}</span>}
                <span className="shrink-0 tabular-nums">· {formatAgo(post.posted_at)}</span>
              </>
            ) : (
              tags.length > 0 && (
                <span className="min-w-0 truncate font-mono text-faint">· {tags.join(", ")}</span>
              )
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 text-meta text-muted">
          {!mobile && comments > 0 && (
            <span className="inline-flex items-center gap-1 tabular-nums" title={`${comments} comments`}>
              <MessageSquare size={13} aria-hidden /> {comments}
              <span className="sr-only">comments</span>
            </span>
          )}
          {!mobile && poster && (
            <span title={poster}>
              <Avatar name={poster} size={22} />
            </span>
          )}
          {!mobile && (
            <span className="w-7 text-right tabular-nums" title={formatDate(post.posted_at)}>
              {formatAgo(post.posted_at)}
            </span>
          )}
          <span onClick={(e) => e.stopPropagation()}>
            <BookmarkButton
              paperId={p.id}
              teamId={teamId}
              userId={userId}
              bookmarked={bookmarked}
              className={cn(
                "tap-target justify-center text-muted hover:text-accent",
                mobile && "-mr-3 h-11 w-11",
              )}
            />
          </span>
        </div>
      </div>
    </div>
  );
}

/** Today, Yesterday, a weekday name within the week, then "12 Sep". */
export function dayLabel(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(d)) / (24 * 60 * 60 * 1000));
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}),
  });
}

function FeedSkeleton() {
  return (
    <div>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="border-b border-border px-[18px] py-3 last:border-b-0">
          <div className="h-3.5 w-2/3 animate-pulse rounded bg-surface-2" />
          <div className="mt-2 h-2.5 w-1/3 animate-pulse rounded bg-surface-2" />
        </div>
      ))}
    </div>
  );
}
