import { type CSSProperties, type RefObject, useCallback, useEffect, useRef, useState } from "react";
import { type QueryKey, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Sparkle, Sparkles, X } from "lucide-react";

import { BookmarkButton } from "@/components/BookmarkButton";
import { Chip } from "@/components/Chip";
import { Cover } from "@/components/Cover";
import { HeadingLink, SectionHeading, TopicDot } from "@/components/home/HomeSection";
import { cardWidth, COL_GAP, type HomeTier } from "@/components/home/layout";
import { useToast } from "@/components/Toast";
import { useSetReadStatus } from "@/hooks/useSetReadStatus";
import type { RecommendationsResult } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Recommendation, RecommendationReason } from "@/lib/types";
import { cn, formatAuthors } from "@/lib/utils";

/** What a card can do besides saving (#182). "read" is for a paper read elsewhere
 *  and counts as reading it; "dismiss" is "Not interested" and counts as nothing. */
type RecAction = "read" | "dismiss";

/** Mark a recommended paper read, or not interested, and offer Undo. The card
 *  leaves the cached Discover list itself, so it stays gone when Home remounts,
 *  and the row isn't refetched, so the other cards don't reshuffle under the
 *  pointer. Undo puts it back where it was. A recommended paper has no
 *  meaningful status row (the API leaves those out), so Undo restores the
 *  defaults: unread, not dismissed. */
function useRecActions(userId: string, teamId: string, rowRef: RefObject<HTMLDivElement | null>) {
  const qc = useQueryClient();
  const toast = useToast();
  const setReadStatus = useSetReadStatus(userId, teamId);

  type Removed = [QueryKey, number, Recommendation];

  function take(paperId: string): Removed[] {
    const removed: Removed[] = [];
    for (const [key, data] of qc.getQueriesData<RecommendationsResult>({
      queryKey: ["recommendations", teamId, "discover"],
    })) {
      const at = data?.results.findIndex((r) => r.post.papers.id === paperId) ?? -1;
      if (!data || at < 0) continue;
      removed.push([key, at, data.results[at]]);
      qc.setQueryData<RecommendationsResult>(key, {
        ...data,
        results: data.results.filter((_, j) => j !== at),
      });
    }
    return removed;
  }

  function putBack(removed: Removed[]) {
    for (const [key, at, rec] of removed) {
      qc.setQueryData<RecommendationsResult>(key, (data) => {
        if (!data || data.results.some((r) => r.post.papers.id === rec.post.papers.id)) return data;
        const results = [...data.results];
        results.splice(Math.min(at, results.length), 0, rec);
        return { ...data, results };
      });
    }
  }

  // The focused button goes with its card; hand focus to the card that takes
  // its place (or the one before, at the end of the row) so a keyboard user
  // carries on from there rather than from the top of the page.
  // Its neighbour is focused before the card goes: cards are keyed, so that
  // element survives the re-render, which a lookup by position afterwards
  // can't promise (it can run before React has removed the card).
  function keepFocus() {
    const row = rowRef.current;
    const card = document.activeElement?.closest("[data-rec-card]");
    if (!row || !card || !row.contains(card)) return;
    const cards = Array.from(row.querySelectorAll<HTMLElement>("[data-rec-card]"));
    const at = cards.indexOf(card as HTMLElement);
    (cards[at + 1] ?? cards[at - 1])?.focus();
  }

  async function dismiss(paperId: string, dismissedAt: string | null) {
    const { error } = await supabase
      .from("paper_status")
      .upsert(
        { user_id: userId, team_id: teamId, paper_id: paperId, dismissed_at: dismissedAt },
        { onConflict: "user_id,paper_id,team_id" },
      );
    return !error;
  }

  async function act(paperId: string, action: RecAction) {
    keepFocus();
    const removed = take(paperId);
    const ok =
      action === "read"
        ? await setReadStatus(paperId, "read")
        : await dismiss(paperId, new Date().toISOString());
    if (!ok) {
      putBack(removed);
      // setReadStatus says so itself.
      if (action === "dismiss") toast({ message: "Couldn’t hide that. Try again." });
      return;
    }
    toast({
      message: action === "read" ? "Marked as read" : "You won’t see this one again",
      actionLabel: "Undo",
      onAction: async () => {
        const undone =
          action === "read" ? await setReadStatus(paperId, "unread") : await dismiss(paperId, null);
        // Throw so the toast stays open and offers Undo again.
        if (!undone) throw new Error("Undo failed");
        putBack(removed);
      },
    });
  }

  return act;
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
  const act = useRecActions(userId, teamId, rowRef);

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
                onAction={(action) => void act(r.post.papers.id, action)}
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
  onAction,
}: {
  rec: Recommendation;
  teamId: string;
  teamName: string;
  userId: string;
  bookmarked: boolean;
  onOpen: () => void;
  onAction: (action: RecAction) => void;
}) {
  const post = rec.post;
  const p = post.papers;
  const tags = (post.tags.length ? post.tags : p.tags).slice(0, 2);
  const topic = null; // no stable topic id yet — see TopicDot
  const eyebrow = [p.venue, p.year].filter(Boolean).join(" · ");

  return (
    // role="button", not <button>: the bookmark inside is a button.
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
        <span className="truncate">{eyebrow}</span>
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
          {/* Spaced so each icon's 44px touch area (.tap-target) stays its own. */}
          <span
            onClick={(e) => e.stopPropagation()}
            className="flex shrink-0 items-center gap-3 [@media(pointer:coarse)]:gap-6"
          >
            <button
              type="button"
              onClick={() => onAction("dismiss")}
              aria-label="Not interested"
              title="Not interested"
              className="tap-target grid place-items-center text-muted transition hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <X size={15} aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => onAction("read")}
              aria-label="Mark as read"
              title="Mark as read"
              className="tap-target grid place-items-center text-muted transition hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <Check size={15} aria-hidden />
            </button>
            <BookmarkButton
              paperId={p.id}
              teamId={teamId}
              userId={userId}
              bookmarked={bookmarked}
              className="tap-target text-muted hover:text-accent"
            />
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
