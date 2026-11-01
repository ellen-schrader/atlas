import { type CSSProperties, useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Sparkle, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";

import { BookmarkButton } from "@/components/BookmarkButton";
import { Chip } from "@/components/Chip";
import { Cover } from "@/components/Cover";
import { HeadingLink, SectionHeading, TopicDot } from "@/components/home/HomeSection";
import { cardWidth, COL_GAP, type HomeTier } from "@/components/home/layout";
import { useToast } from "@/components/Toast";
import { supabase } from "@/lib/supabase";
import type { Recommendation, RecommendationReason } from "@/lib/types";
import { cn, formatAuthors } from "@/lib/utils";

/** 👍 "More like this", 👎 "Not interested", or no answer (#182). */
type RecFeedback = "up" | "down" | undefined;

interface Answer {
  rec: Recommendation;
  at: number; // where the card sat, to keep it there if a refetch drops it
  shown: RecFeedback;
}

/** 👍 / 👎 on a recommendation (#182), both private to you, both switches on
 *  the card: click again to take it back, click the other to change your mind.
 *  👍 "More like this" (paper_status.liked_at) is a taste signal that doesn't
 *  touch your reading list. 👎 "Not interested" (dismissed_at) is no signal at
 *  all; the card dims but stays, so it can be taken back.
 *
 *  Answers live here, for this visit to Home, not in the query cache: the API
 *  leaves answered papers out, so a refetch (a Mark read elsewhere on Home, the
 *  tab regaining focus) would otherwise drop a card mid-thought. An answered
 *  card keeps its place until Home is next opened. One card's writes go out in
 *  click order; if one fails, the card shows the last answer the server took,
 *  unless the user has clicked again since. */
function useRecFeedback(userId: string, teamId: string) {
  const toast = useToast();
  const [answers, setAnswers] = useState<ReadonlyMap<string, Answer>>(() => new Map());
  const chains = useRef(new Map<string, Promise<boolean>>());
  const clicks = useRef(new Map<string, number>());
  const saved = useRef(new Map<string, RecFeedback>());

  function show(rec: Recommendation, at: number, shown: RecFeedback) {
    setAnswers((cur) => new Map(cur).set(rec.post.papers.id, { rec, at, shown }));
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

  async function answer(rec: Recommendation, at: number, next: RecFeedback) {
    const id = rec.post.papers.id;
    const click = (clicks.current.get(id) ?? 0) + 1;
    clicks.current.set(id, click);
    show(rec, at, next);
    const run = () => write(id, next);
    const done = (chains.current.get(id) ?? Promise.resolve(true)).then(run, run);
    chains.current.set(id, done);
    const ok = await done;
    if (chains.current.get(id) === done) chains.current.delete(id);
    if (ok) {
      saved.current.set(id, next);
      return;
    }
    // A recommended paper starts unanswered: the API leaves answered ones out.
    if (clicks.current.get(id) === click) show(rec, at, saved.current.get(id));
    toast({ message: "Couldn’t save that. Try again." });
  }

  // Saving a paper clears its 👎 in the database (paper_status_clear_dismissal):
  // a paper you saved is one you're interested in. The card follows.
  function savedPaper(rec: Recommendation, at: number) {
    const id = rec.post.papers.id;
    if (answers.get(id)?.shown !== "down") return;
    clicks.current.set(id, (clicks.current.get(id) ?? 0) + 1);
    saved.current.set(id, undefined);
    show(rec, at, undefined);
  }

  return { answers, answer, savedPaper };
}

/** The row's cards: the API's, plus any answered this visit that a refetch
 *  has since left out, back where they were. */
function withAnswered(results: Recommendation[], answers: ReadonlyMap<string, Answer>) {
  const list = [...results];
  const ids = new Set(results.map((r) => r.post.papers.id));
  for (const [id, a] of [...answers].sort((x, y) => x[1].at - y[1].at)) {
    if (!ids.has(id)) list.splice(Math.min(a.at, list.length), 0, a.rec);
  }
  return list;
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
  const { answers, answer, savedPaper } = useRecFeedback(userId, teamId);
  const cards = withAnswered(recs.results, answers);

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
  }, [measure, cards.length]);

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
  const right = !mobile && cards.length > perPage && (
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
      ) : cards.length > 0 ? (
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
          {cards.map((r, at) => (
            <div key={r.post.id} className="flex shrink-0 snap-start" style={itemStyle}>
              <RecCard
                rec={r}
                teamId={teamId}
                teamName={teamName}
                userId={userId}
                bookmarked={bookmarkedIds.has(r.post.papers.id)}
                onOpen={() => onOpen(r.post.papers.id)}
                feedback={answers.get(r.post.papers.id)?.shown}
                onAnswer={(next) => void answer(r, at, next)}
                onSaved={(on) => on && savedPaper(r, at)}
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
  feedback,
  onAnswer,
  onSaved,
}: {
  rec: Recommendation;
  teamId: string;
  teamName: string;
  userId: string;
  bookmarked: boolean;
  onOpen: () => void;
  feedback: RecFeedback;
  onAnswer: (next: RecFeedback) => void;
  onSaved: (saved: boolean) => void;
}) {
  const post = rec.post;
  const p = post.papers;
  const tags = (post.tags.length ? post.tags : p.tags).slice(0, 2);
  const topic = null; // no stable topic id yet — see TopicDot
  const eyebrow = [p.venue, p.year].filter(Boolean).join(" · ");
  const down = feedback === "down";
  // A 👎 card stays where it is, faded but readable, for the rest of the visit.
  const fade = cn("transition-opacity", down && "opacity-60");

  return (
    // role="button", not <button>: the bookmark and thumbs inside are buttons.
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
            onSaved={onSaved}
            className="tap-target h-8 w-8 justify-center rounded-full text-muted hover:bg-surface-2 hover:text-accent"
          />
        </span>
      </div>
      <div className={fade}>
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
      </div>
      <div className="mt-auto pt-3">
        <div className="flex items-start gap-2 border-t border-border pt-3">
          {/* Polite live region: a screen reader hears what 👎 did, as it
              would a toast. Its first content isn't announced. */}
          <div aria-live="polite" className="flex min-w-0 flex-1 items-start gap-2">
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
          </div>
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
              on={feedback === "up"}
              onClick={() => onAnswer(feedback === "up" ? undefined : "up")}
            />
            {/* Off on a saved paper: saving says you're interested, and the
                database clears a 👎 on a saved paper. */}
            <ThumbButton
              label={bookmarked ? "Saved to your reading list" : "Not interested"}
              Icon={ThumbsDown}
              on={down}
              disabled={bookmarked}
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
  disabled = false,
  onClick,
}: {
  label: string;
  Icon: typeof ThumbsUp;
  on: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={on}
      aria-label={label}
      title={label}
      className={cn(
        "tap-target grid h-8 w-8 place-items-center rounded-full transition hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        on ? "text-accent" : "text-muted hover:text-fg",
        "disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted",
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
