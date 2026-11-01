import { type CSSProperties, useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Sparkle, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";

import { BookmarkButton } from "@/components/BookmarkButton";
import { Chip } from "@/components/Chip";
import { Cover } from "@/components/Cover";
import { HeadingLink, SectionHeading, TopicDot } from "@/components/home/HomeSection";
import { cardWidth, COL_GAP, type HomeTier } from "@/components/home/layout";
import { useToast } from "@/components/Toast";
import type { RecommendationsResult } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Recommendation, RecommendationReason, RecFeedback } from "@/lib/types";
import { cn, formatAuthors } from "@/lib/utils";

/** 👍 / 👎 on a recommendation (#182), both private to you, both switches on
 *  the card: click again to take it back, click the other to change your mind.
 *  👍 "More like this" (paper_status.liked_at) is a taste signal that doesn't
 *  touch your reading list. 👎 "Not interested" (dismissed_at) is no signal at
 *  all; the card dims but stays, so it can be taken back. Either way the paper
 *  isn't offered again once the row refreshes.
 *
 *  The answer lives in the cached Discover list, so it survives Home
 *  remounting, and the row isn't refetched, so the cards don't reshuffle under
 *  the pointer. One card's writes go out in click order, so quick clicks can't
 *  land the other way round (the database keeps the later answer as well). */
function useRecFeedback(userId: string, teamId: string) {
  const qc = useQueryClient();
  const toast = useToast();
  const chains = useRef(new Map<string, Promise<unknown>>());

  // `from`: change only a card still showing this answer.
  function show(paperId: string, feedback: RecFeedback, from?: { feedback: RecFeedback }) {
    qc.setQueriesData<RecommendationsResult>(
      { queryKey: ["recommendations", teamId, "discover"] },
      (data) =>
        data && {
          ...data,
          results: data.results.map((r) =>
            r.post.papers.id === paperId && (!from || r.feedback === from.feedback)
              ? { ...r, feedback }
              : r,
          ),
        },
    );
  }

  async function write(paperId: string, feedback: RecFeedback) {
    const now = new Date().toISOString();
    const { error } = await supabase.from("paper_status").upsert(
      {
        user_id: userId,
        team_id: teamId,
        paper_id: paperId,
        liked_at: feedback === "up" ? now : null,
        dismissed_at: feedback === "down" ? now : null,
      },
      { onConflict: "user_id,paper_id,team_id" },
    );
    return !error;
  }

  return async function answer(paperId: string, was: RecFeedback, next: RecFeedback) {
    show(paperId, next);
    const run = () => write(paperId, next);
    const done = (chains.current.get(paperId) ?? Promise.resolve()).then(run, run);
    chains.current.set(paperId, done);
    if (!(await done)) {
      // Back to how it was, unless something newer has been clicked since.
      show(paperId, was, { feedback: next });
      toast({ message: "Couldn’t save that. Try again." });
    }
  };
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
  const answer = useRecFeedback(userId, teamId);

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
                onAnswer={(next) => void answer(r.post.papers.id, r.feedback, next)}
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
  onAnswer,
}: {
  rec: Recommendation;
  teamId: string;
  teamName: string;
  userId: string;
  bookmarked: boolean;
  onOpen: () => void;
  onAnswer: (next: RecFeedback) => void;
}) {
  const post = rec.post;
  const p = post.papers;
  const tags = (post.tags.length ? post.tags : p.tags).slice(0, 2);
  const topic = null; // no stable topic id yet — see TopicDot
  const eyebrow = [p.venue, p.year].filter(Boolean).join(" · ");
  const down = rec.feedback === "down";
  // A 👎 card stays where it is, faded, until the row refreshes.
  const fade = cn("transition-opacity", down && "opacity-40");

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
      <div className={cn("absolute inset-x-0 top-0 h-1.5 opacity-75", down && "opacity-30")} aria-hidden>
        <Cover seed={p.id} />
      </div>
      <div className="flex min-w-0 items-center gap-2 text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
        <TopicDot topic={topic} />
        <span className={cn("min-w-0 flex-1 truncate", fade)}>{eyebrow}</span>
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
      <h3
        className={cn(
          "mt-2.5 line-clamp-3 h-[57px] text-card font-semibold leading-[19px] tracking-snug",
          fade,
        )}
      >
        {p.title ?? p.url}
      </h3>
      <div className={cn("mt-2 truncate text-meta text-muted", fade)}>
        {formatAuthors(p.authors, 3)}
      </div>
      <div className={cn("mt-2 flex h-6 min-w-0 gap-1.5", fade)}>
        {tags[0] && <Chip className="shrink-0">{tags[0]}</Chip>}
        {tags[1] && (
          <Chip className="min-w-0 overflow-hidden">
            <span className="min-w-0 truncate">{tags[1]}</span>
          </Chip>
        )}
      </div>
      <div className="mt-auto pt-3">
        <div className="flex items-start gap-2 border-t border-border pt-3">
          {down ? (
            // Says what 👎 did, so taking it back is the obvious next move.
            <p className="h-[34px] flex-1 text-meta leading-[17px] text-muted">
              You won’t see this again
            </p>
          ) : rec.reason ? (
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
            <ThumbButton
              label="More like this"
              Icon={ThumbsUp}
              on={rec.feedback === "up"}
              onClick={() => onAnswer(rec.feedback === "up" ? undefined : "up")}
            />
            <ThumbButton
              label="Not interested"
              Icon={ThumbsDown}
              on={down}
              onClick={() => onAnswer(down ? undefined : "down")}
            />
          </span>
        </div>
      </div>
    </div>
  );
}

/** 👍 or 👎: outlined until chosen, then filled in the accent colour. */
function ThumbButton({
  label,
  Icon,
  on,
  onClick,
}: {
  label: string;
  Icon: typeof ThumbsUp;
  on: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      aria-label={label}
      title={label}
      className={cn(
        "tap-target grid h-8 w-8 place-items-center rounded-full transition hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        on ? "text-accent" : "text-muted hover:text-fg",
      )}
    >
      <Icon size={15} fill={on ? "currentColor" : "none"} aria-hidden />
    </button>
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
