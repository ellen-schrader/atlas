import { type CSSProperties, type RefObject, useCallback, useEffect, useRef, useState } from "react";
import { type QueryKey, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Sparkle, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";

import { BookmarkButton } from "@/components/BookmarkButton";
import { Chip } from "@/components/Chip";
import { Cover } from "@/components/Cover";
import { HeadingLink, SectionHeading, TopicDot } from "@/components/home/HomeSection";
import { cardWidth, COL_GAP, type HomeTier } from "@/components/home/layout";
import { useToast } from "@/components/Toast";
import type { RecommendationsResult } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Recommendation, RecommendationReason } from "@/lib/types";
import { cn, formatAuthors } from "@/lib/utils";

/** 👍 / 👎 on a recommendation (#182), both private to you. 👍 "More like this"
 *  (paper_status.liked_at) is a taste signal that doesn't touch your reading
 *  list; the card stays, its thumb filled, until the row next refreshes. 👎
 *  "Not interested" (dismissed_at) is no signal at all, and the card goes at
 *  once. Either way the server won't offer the paper again, so both toasts
 *  carry an Undo: after the refresh it is the only way back.
 *
 *  Both edit the cached Discover list rather than refetching it, so the other
 *  cards don't reshuffle under the pointer. One card's writes go out in click
 *  order, so a quick 👍 then 👎 can't land the other way round. */
function useRecFeedback(userId: string, teamId: string, rowRef: RefObject<HTMLDivElement | null>) {
  const qc = useQueryClient();
  const toast = useToast();
  const key = ["recommendations", teamId, "discover"];
  const chains = useRef(new Map<string, Promise<unknown>>());
  // When each 👍 on screen was given, so undoing a 👎 can put it back as it was.
  const likedAt = useRef(new Map<string, string>());

  function inOrder<T>(paperId: string, run: () => Promise<T>): Promise<T> {
    const next = (chains.current.get(paperId) ?? Promise.resolve()).then(run, run);
    chains.current.set(paperId, next);
    return next;
  }

  type Removed = [QueryKey, number, Recommendation];

  function edit(paperId: string, change: (rec: Recommendation) => Recommendation) {
    qc.setQueriesData<RecommendationsResult>({ queryKey: key }, (data) =>
      data && {
        ...data,
        results: data.results.map((r) => (r.post.papers.id === paperId ? change(r) : r)),
      },
    );
  }

  function take(paperId: string): Removed[] {
    const removed: Removed[] = [];
    for (const [k, data] of qc.getQueriesData<RecommendationsResult>({ queryKey: key })) {
      const at = data?.results.findIndex((r) => r.post.papers.id === paperId) ?? -1;
      if (!data || at < 0) continue;
      removed.push([k, at, data.results[at]]);
      qc.setQueryData<RecommendationsResult>(k, {
        ...data,
        results: data.results.filter((_, j) => j !== at),
      });
    }
    return removed;
  }

  function putBack(removed: Removed[]) {
    for (const [k, at, rec] of removed) {
      qc.setQueryData<RecommendationsResult>(k, (data) => {
        if (!data || data.results.some((r) => r.post.papers.id === rec.post.papers.id)) return data;
        const results = [...data.results];
        results.splice(Math.min(at, results.length), 0, rec);
        return { ...data, results };
      });
    }
  }

  // The focused 👎 goes with its card, so a keyboard user would land at the top
  // of the page. Its neighbour is focused before the card goes: cards are keyed,
  // so that element survives the re-render, which a lookup by position
  // afterwards can't promise (it can run before React has removed the card).
  function keepFocus() {
    const row = rowRef.current;
    const card = document.activeElement?.closest("[data-rec-card]");
    if (!row || !card || !row.contains(card)) return;
    const cards = Array.from(row.querySelectorAll<HTMLElement>("[data-rec-card]"));
    const at = cards.indexOf(card as HTMLElement);
    (cards[at + 1] ?? cards[at - 1])?.focus();
  }

  async function write(paperId: string, fields: Record<string, string | null>) {
    const { error } = await supabase
      .from("paper_status")
      .upsert(
        { user_id: userId, team_id: teamId, paper_id: paperId, ...fields },
        { onConflict: "user_id,paper_id,team_id" },
      );
    return !error;
  }

  async function like(paperId: string, on: boolean) {
    edit(paperId, (r) => ({ ...r, liked: on }));
    const now = new Date().toISOString();
    if (on) likedAt.current.set(paperId, now);
    else likedAt.current.delete(paperId);
    const ok = await inOrder(paperId, () => write(paperId, { liked_at: on ? now : null }));
    if (!ok) {
      // Only if nothing newer has been clicked on this card since.
      edit(paperId, (r) => (r.liked === on ? { ...r, liked: !on } : r));
      toast({ message: "Couldn’t save that. Try again." });
      return;
    }
    if (on) {
      toast({
        message: "You’ll see more like this",
        actionLabel: "Undo",
        onAction: async () => {
          likedAt.current.delete(paperId);
          const undone = await inOrder(paperId, () => write(paperId, { liked_at: null }));
          if (!undone) throw new Error("Undo failed");
          edit(paperId, (r) => ({ ...r, liked: false }));
        },
      });
    }
  }

  async function dislike(paperId: string) {
    keepFocus();
    const removed = take(paperId);
    const liked = likedAt.current.get(paperId) ?? null;
    likedAt.current.delete(paperId);
    // A 👎 replaces a 👍 given a moment ago on the same card.
    const dismissed = { dismissed_at: new Date().toISOString(), liked_at: null };
    if (!(await inOrder(paperId, () => write(paperId, dismissed)))) {
      putBack(removed);
      toast({ message: "Couldn’t hide that. Try again." });
      return;
    }
    toast({
      message: "You won’t see this one again",
      actionLabel: "Undo",
      onAction: async () => {
        // Back as it was, 👍 included. Throw so the toast stays open and offers
        // Undo again.
        const back = { dismissed_at: null, liked_at: liked };
        if (!(await inOrder(paperId, () => write(paperId, back)))) throw new Error("Undo failed");
        if (liked) likedAt.current.set(paperId, liked);
        putBack(removed.map(([k, at, rec]) => [k, at, { ...rec, liked: !!liked }]));
      },
    });
  }

  return { like, dislike };
}

interface RecsState {
  results: Recommendation[];
  isLoading: boolean;
  isError: boolean;
  waking: boolean;
}

/** "Recommended for you": a horizontal, snap-scrolling row of cards, each one
 *  grid column wide, so card edges line up with the blocks above and below. */
export function RecommendationsRow({
  recs,
  tier,
  perPage,
  teamId,
  teamName,
  hasProfile,
  userId,
  bookmarkedIds,
  onOpen,
  onTune,
}: {
  recs: RecsState;
  tier: HomeTier;
  perPage: number;
  teamId: string;
  teamName: string;
  /** Without a research profile (and, today, little Atlas engagement) the row
   *  is just the newest papers; the header link says what would fix that. */
  hasProfile: boolean;
  userId: string;
  bookmarkedIds: Set<string>;
  onOpen: (paperId: string) => void;
  onTune: () => void;
}) {
  const rowRef = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ start: true, end: true });
  const mobile = tier === "mobile";
  const feedback = useRecFeedback(userId, teamId, rowRef);

  const measure = useCallback(() => {
    const el = rowRef.current;
    if (!el) return;
    setEdges({
      start: el.scrollLeft <= 1,
      end: el.scrollLeft + el.clientWidth >= el.scrollWidth - 1,
    });
  }, []);

  useEffect(() => {
    measure();
    const el = rowRef.current;
    if (!el) return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure, recs.results.length]);

  // One click = one page of cards. The row's width is exactly perPage cards plus
  // their gaps, so a page is the row width plus one gap.
  function page(dir: -1 | 1) {
    const el = rowRef.current;
    if (!el) return;
    el.scrollBy({ left: dir * (el.clientWidth + COL_GAP), behavior: "smooth" });
  }

  const itemStyle: CSSProperties = { width: mobile ? "84%" : cardWidth(perPage) };

  // Arrows alone on the right edge; Tune sits with the title, where the Lab feed
  // keeps its filter.
  const right = !mobile && recs.results.length > perPage && (
    <>
      <ArrowButton dir="left" disabled={edges.start} onClick={() => page(-1)} />
      <ArrowButton dir="right" disabled={edges.end} onClick={() => page(1)} />
    </>
  );

  return (
    <section className="min-w-0">
      <SectionHeading
        title="Recommended for you"
        controls={
          <HeadingLink onClick={onTune}>{hasProfile ? "Tune" : "Describe your research"}</HeadingLink>
        }
        right={right}
      />

      {recs.isLoading ? (
        <div className="flex gap-6 overflow-hidden">
          {Array.from({ length: mobile ? 2 : perPage }).map((_, i) => (
            <div key={i} className="shrink-0" style={itemStyle}>
              <RecCardSkeleton />
            </div>
          ))}
        </div>
      ) : recs.results.length > 0 ? (
        <div
          ref={rowRef}
          onScroll={measure}
          className={cn(
            "flex snap-x snap-mandatory gap-6 overflow-x-auto scroll-smooth",
            "[-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
            // Phones: bleed to the screen edges so the next card peeks in.
            mobile && "-mx-4 scroll-px-4 px-4",
          )}
        >
          {recs.results.map((r) => (
            <div key={r.post.id} className="flex shrink-0 snap-start" style={itemStyle}>
              <RecCard
                rec={r}
                teamId={teamId}
                teamName={teamName}
                userId={userId}
                bookmarked={bookmarkedIds.has(r.post.papers.id)}
                onOpen={() => onOpen(r.post.papers.id)}
                onLike={(on) => void feedback.like(r.post.papers.id, on)}
                onDislike={() => void feedback.dislike(r.post.papers.id)}
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-start gap-2 rounded-card border border-dashed border-border bg-surface-2 p-5">
          <span className="inline-flex items-center gap-2 text-sm font-medium">
            <Sparkles size={15} className="text-accent" />
            {recs.waking
              ? "Loading recommendations…"
              : recs.isError
                ? "Couldn’t load recommendations."
                : "No new papers to recommend yet."}
          </span>
          <p className="text-xs text-muted">
            {recs.waking
              ? "This can take up to a minute after a quiet spell."
              : recs.isError
                ? "Try again in a minute."
                : "Add a short research profile in Settings to get recommendations."}
          </p>
          {!recs.isError && (
            <button
              onClick={onTune}
              className="mt-1 rounded-control bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg transition hover:brightness-110"
            >
              Set up your profile
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function ArrowButton({
  dir,
  disabled,
  onClick,
}: {
  dir: "left" | "right";
  disabled: boolean;
  onClick: () => void;
}) {
  const Icon = dir === "left" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={dir === "left" ? "Scroll left" : "Scroll right"}
      className="tap-target grid h-7 w-7 place-items-center rounded-full border border-border text-muted transition hover:border-border-strong hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-40 disabled:hover:border-border disabled:hover:text-muted"
    >
      <Icon size={14} />
    </button>
  );
}

/** One recommendation. Title and reason have FIXED heights (57px / 34px) so the
 *  footers line up across a row whatever the titles' lengths. */
export function RecCard({
  rec,
  teamId,
  teamName,
  userId,
  bookmarked,
  onOpen,
  onLike,
  onDislike,
}: {
  rec: Recommendation;
  teamId: string;
  teamName: string;
  userId: string;
  bookmarked: boolean;
  onOpen: () => void;
  onLike: (on: boolean) => void;
  onDislike: () => void;
}) {
  const post = rec.post;
  const p = post.papers;
  const tags = (post.tags.length ? post.tags : p.tags).slice(0, 2);
  const topic = null; // no stable topic id yet — see TopicDot
  const eyebrow = [p.venue, p.year].filter(Boolean).join(" · ");

  return (
    // role="button", not <button>: the bookmark and thumbs inside are buttons.
    <div
      role="button"
      tabIndex={0}
      data-rec-card
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className="relative box-border flex w-full cursor-pointer flex-col overflow-hidden rounded-card border border-border bg-surface p-4 pt-[22px] text-left transition hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      {/* The same generative spine as PaperCard, so a paper wears the same colour
          on Home as in Papers. Stronger than PaperCard's 0.35: a row of three to
          five cards doesn't shout the way a full grid does. */}
      <div className="absolute inset-x-0 top-0 h-1.5 opacity-75" aria-hidden>
        <Cover seed={p.id} />
      </div>
      <div className="flex min-w-0 items-center gap-2 text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
        <TopicDot topic={topic} />
        <span className="min-w-0 flex-1 truncate">{eyebrow}</span>
        {/* Saving acts on the paper, so it sits apart from the thumbs, which
            answer the recommendation. Negative margins keep the eyebrow's
            height and the icon's alignment with the card's edge. */}
        <span
          onClick={(e) => e.stopPropagation()}
          className="-my-2 -mr-2 shrink-0 normal-case tracking-normal"
        >
          <BookmarkButton
            paperId={p.id}
            teamId={teamId}
            userId={userId}
            bookmarked={bookmarked}
            className="tap-target h-8 w-8 justify-center rounded-full text-muted hover:bg-surface-2 hover:text-accent"
          />
        </span>
      </div>
      <h3 className="mt-2.5 line-clamp-3 h-[57px] text-card font-semibold leading-[19px] tracking-snug">
        {p.title ?? p.url}
      </h3>
      <div className="mt-2 truncate text-meta text-muted">{formatAuthors(p.authors, 3)}</div>
      <div className="mt-2 flex h-6 min-w-0 gap-1.5">
        {tags[0] && <Chip className="shrink-0">{tags[0]}</Chip>}
        {tags[1] && (
          <Chip className="min-w-0 overflow-hidden">
            <span className="min-w-0 truncate">{tags[1]}</span>
          </Chip>
        )}
      </div>
      <div className="mt-auto pt-3">
        <div className="flex items-start gap-2 border-t border-border pt-3">
          {rec.reason ? (
            <>
              <Sparkle size={12} aria-hidden className="mt-[3px] shrink-0 fill-accent text-accent" />
              <p className="line-clamp-2 h-[34px] flex-1 text-meta leading-[17px] text-muted">
                <ReasonText reason={rec.reason} teamName={teamName} />
              </p>
            </>
          ) : (
            <span className="h-[34px] flex-1" />
          )}
          {/* 32px round targets that show where they end, so a near miss doesn't
              open the paper; on touch, spaced so each 44px area (.tap-target)
              stays its own. Negative margins line the icons up with the text. */}
          <span
            onClick={(e) => e.stopPropagation()}
            className="-mr-2 -mt-2 flex shrink-0 items-center gap-1 [@media(pointer:coarse)]:gap-3"
          >
            <button
              type="button"
              onClick={() => onLike(!rec.liked)}
              aria-pressed={!!rec.liked}
              aria-label="More like this"
              title="More like this"
              className={cn(
                "tap-target grid h-8 w-8 place-items-center rounded-full transition hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                rec.liked ? "text-accent" : "text-muted hover:text-fg",
              )}
            >
              <ThumbsUp size={15} fill={rec.liked ? "currentColor" : "none"} aria-hidden />
            </button>
            <button
              type="button"
              onClick={onDislike}
              aria-label="Not interested"
              title="Not interested"
              className="tap-target grid h-8 w-8 place-items-center rounded-full text-muted transition hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <ThumbsDown size={15} aria-hidden />
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}

/** The three reason patterns of docs/dashboard.md §3.4, referenced item in --fg. */
function ReasonText({ reason, teamName }: { reason: RecommendationReason; teamName: string }) {
  const ref = <span className="text-fg">{reason.ref_label}</span>;
  switch (reason.kind) {
    case "similar_saved":
      return <>Similar to {ref}, which you saved</>;
    case "similar_posted":
      return <>Similar to {ref}, which you shared</>;
    case "similar_read":
      return <>Similar to {ref}, which you read</>;
    case "similar_reacted":
      return <>Similar to {ref}, which you reacted to</>;
    case "similar_liked":
      return <>Similar to {ref}, which you liked</>;
    case "similar_discussed":
      return <>Similar to {ref}, which you discussed</>;
    case "similar_reading":
      return <>Similar to {ref}, which you’re reading</>;
    case "profile": {
      if (!reason.ref_label) return <>Matches your research profile</>;
      // Tags are slugs ("spatial-transcriptomics"); the sentence wants words.
      const words = (t: string) => t.replace(/[-_]+/g, " ");
      const extra = reason.extra_labels?.[0];
      return (
        <>
          Matches <span className="text-fg">{words(reason.ref_label)}</span>
          {extra && (
            <>
              {" "}
              and <span className="text-fg">{words(extra)}</span>
            </>
          )}{" "}
          in your research profile
        </>
      );
    }
    case "engagement":
      // The taste can come from reactions or comments too, not only saves.
      return <>Based on what you’ve read</>;
    case "new":
      return (
        <>
          New in <span className="text-fg">{teamName}</span>
          {reason.ref_label && <> · shared by {reason.ref_label}</>}
        </>
      );
    case "tag": {
      const extra = reason.extra_labels?.[0];
      return extra ? (
        <>
          Tagged {ref} and <span className="text-fg">{extra}</span>, which you follow
        </>
      ) : (
        <>Tagged {ref}, which you follow</>
      );
    }
    case "author":
      return <>By {ref}, who you follow</>;
  }
}

function RecCardSkeleton() {
  return (
    <div className="w-full rounded-card border border-border bg-surface p-4">
      <div className="h-2.5 w-1/3 animate-pulse rounded bg-surface-2" />
      <div className="mt-3 h-[57px] w-full animate-pulse rounded-md bg-surface-2" />
      <div className="mt-2 h-2.5 w-2/3 animate-pulse rounded bg-surface-2" />
      <div className="mt-3 h-5 w-1/2 animate-pulse rounded bg-surface-2" />
      <div className="mt-3 h-[47px] w-full animate-pulse rounded-md bg-surface-2" />
    </div>
  );
}
