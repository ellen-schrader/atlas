import { type ReactNode, type RefObject, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { AtSign, Bookmark, Check, ChevronLeft, ChevronRight, Sparkles } from "lucide-react";

import { InviteCode } from "@/components/InviteCode";
import { PaperCard } from "@/components/PaperCard";
import { PaperListRow } from "@/components/PaperListRow";
import { usePaperModal } from "@/components/PaperModal";
import { useEngagementCounts } from "@/hooks/useEngagementCounts";
import { isTransientApiError } from "@/lib/api";
import { useMentionActions } from "@/hooks/useMentionActions";
import { useMentions } from "@/hooks/useMentions";
import { usePaperSearch } from "@/hooks/usePaperSearch";
import { useReadingList } from "@/hooks/useReadingList";
import { useReadPapers } from "@/hooks/useReadPapers";
import { useRecommendations } from "@/hooks/useRecommendations";
import { supabase } from "@/lib/supabase";
import { cn, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export default function Dashboard() {
  const { team, userId, displayName } = useAppContext();
  const { openPaper } = usePaperModal();
  const navigate = useNavigate();
  const recRowRef = useRef<HTMLDivElement>(null);

  const search = usePaperSearch(team.id, "");
  const posts = (search.data?.pages ?? []).flat();
  const { data: counts } = useEngagementCounts(
    team.id,
    posts.map((p) => p.papers.id),
  );
  const { data: mentions } = useMentions(userId);
  const { data: toRead } = useReadingList(userId, team.id);
  const { data: readIds } = useReadPapers(userId, team.id);
  const recs = useRecommendations(team.id, "discover", 6);
  const recResults = recs.data?.results ?? [];
  const { data: recCounts } = useEngagementCounts(
    team.id,
    recResults.map((r) => r.post.papers.id),
  );
  const qc = useQueryClient();
  const { markSeen, markAllSeen } = useMentionActions(userId);

  async function markPaperRead(paperId: string) {
    await supabase
      .from("paper_status")
      .update({ status: "read" })
      .eq("user_id", userId)
      .eq("team_id", team.id)
      .eq("paper_id", paperId);
    void qc.invalidateQueries({ queryKey: ["reading-list"] });
    void qc.invalidateQueries({ queryKey: ["read-papers"] });
  }

  const firstName = displayName.split(/[\s@]/)[0];
  const unseenMentions = (mentions ?? []).filter((m) => !m.seen_at);
  const bookmarkedIds = new Set((toRead ?? []).map((r) => r.paper_id));
  const active = posts.filter((p) => (counts?.[p.papers.id]?.comments ?? 0) > 0).slice(0, 2);
  const recent = posts.slice(0, 6);

  // Mentions first; a paper that's both mentioned and on the reading list shows
  // once (as the mention), so a single paper never occupies two slots.
  const seen = new Set<string>();
  const attention: AttentionItem[] = [];
  for (const m of unseenMentions) {
    if (seen.has(m.paper_id)) continue;
    seen.add(m.paper_id);
    attention.push({
      key: `m-${m.id}`,
      accent: true,
      icon: <AtSign size={15} />,
      lead: "Mentioned you",
      title: m.papers?.title ?? "A paper",
      sub: formatRelative(m.created_at),
      onOpen: () => {
        void markSeen(m.paper_id);
        openPaper(m.paper_id);
      },
      onClear: () => void markSeen(m.paper_id),
    });
  }
  for (const r of toRead ?? []) {
    if (seen.has(r.paper_id)) continue;
    seen.add(r.paper_id);
    attention.push({
      key: `r-${r.paper_id}`,
      accent: false,
      icon: <Bookmark size={15} />,
      lead: "On your reading list",
      title: r.papers?.title ?? "A paper",
      sub: [r.papers?.venue, r.papers?.year].filter(Boolean).join(" · "),
      onOpen: () => openPaper(r.paper_id),
      onClear: () => void markPaperRead(r.paper_id),
    });
  }
  const attentionItems = attention.slice(0, 6);

  const empty = !search.isLoading && posts.length === 0;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-10 p-8">
      <header>
        <h1 className="text-display font-serif font-semibold tracking-tight">
          {greeting()}, {firstName}
        </h1>
        <p className="mt-1.5 text-sm text-muted">What’s moving in {team.name}.</p>
      </header>

      {empty && (
        <div className="flex flex-col items-center gap-3 rounded-card border border-dashed border-border-strong px-6 py-16 text-center">
          <div className="font-semibold">No papers in {team.name} yet</div>
          <p className="text-sm text-muted">Post the first one from the Papers page.</p>
          <button
            onClick={() => navigate("/papers")}
            className="rounded-control bg-accent px-4 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110"
          >
            Go to Papers
          </button>
          <div className="mt-3 flex w-full max-w-xs flex-col items-center gap-2 border-t border-border pt-5">
            <span className="text-xs text-muted">Or invite your lab with this join code</span>
            <InviteCode code={team.slug} />
          </div>
        </div>
      )}

      {attentionItems.length > 0 && (
        <Section
          title="Needs your attention"
          count={attentionItems.length}
          action={
            unseenMentions.length > 0
              ? { label: "Mark all read", onClick: () => void markAllSeen() }
              : undefined
          }
        >
          <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
            {attentionItems.map((a) => (
              <AttentionCard key={a.key} item={a} />
            ))}
          </div>
        </Section>
      )}

      {!empty && (
        <Section
          title="Recommended for you"
          action={{ label: "Reading list", onClick: () => navigate("/reading") }}
        >
          {/* The cold-start notice sits OUTSIDE the has-results branch on purpose: a
              brand-new lab is exactly the case it explains, and that lab often has no
              recommendations to show yet. Nesting it under `recResults.length > 0` hid
              it from the only people who needed it. */}
          {recs.data?.cold_start && (
            <p className="mb-3 text-xs text-muted">
              Newest first — Atlas doesn’t know your lab’s taste yet. Save and react to a few papers
              and this becomes yours, or{" "}
              <button
                onClick={() => navigate("/settings")}
                className="font-medium text-accent hover:underline"
              >
                describe your research
              </button>{" "}
              to give it a head start.
            </p>
          )}
          {recs.isLoading ? (
            <CardSkeleton />
          ) : recResults.length > 0 ? (
            <>
              <div className="group/rec relative">
                <ScrollArrow side="left" rowRef={recRowRef} />
                <div
                  ref={recRowRef}
                  className="flex snap-x gap-4 overflow-x-auto scroll-smooth pb-2 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
                >
                  {recResults.map((r) => (
                    <div key={r.post.id} className="w-[300px] shrink-0 snap-start">
                      <PaperCard
                        post={r.post}
                        reactions={recCounts?.[r.post.papers.id]?.reactions ?? 0}
                        comments={recCounts?.[r.post.papers.id]?.comments ?? 0}
                        onOpen={() => openPaper(r.post.papers.id)}
                        teamId={team.id}
                        userId={userId}
                        bookmarked={bookmarkedIds.has(r.post.papers.id)}
                      />
                    </div>
                  ))}
                </div>
                <ScrollArrow side="right" rowRef={recRowRef} />
              </div>
            </>
          ) : (
            <div className="flex flex-col items-start gap-2 rounded-card border border-dashed border-border bg-surface-2 p-5">
              <span className="inline-flex items-center gap-2 text-sm font-medium">
                <Sparkles size={15} className="text-accent" />
                {recs.isError
                  ? isTransientApiError(recs.error)
                    ? "Waking the paper service…"
                    : "Recommendations are unavailable right now."
                  : "No new papers to recommend yet."}
              </span>
              <p className="text-xs text-muted">
                {recs.isError
                  ? isTransientApiError(recs.error)
                    ? "It sleeps when nobody’s around — recommendations will appear here shortly."
                    : "The recommendation service isn’t reachable — try again shortly."
                  : "Describe your research in Settings and engage with papers, and we’ll surface the ones worth your time."}
              </p>
              {!recs.isError && (
                <button
                  onClick={() => navigate("/settings")}
                  className="mt-1 rounded-control bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg transition hover:brightness-110"
                >
                  Set up your profile
                </button>
              )}
            </div>
          )}
        </Section>
      )}

      {active.length > 0 && (
        <Section title="Active discussions" action={{ label: "All papers", onClick: () => navigate("/papers") }}>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
            {active.map((post) => (
              <PaperCard
                key={post.id}
                post={post}
                reactions={counts?.[post.papers.id]?.reactions ?? 0}
                comments={counts?.[post.papers.id]?.comments ?? 0}
                onOpen={() => openPaper(post.papers.id)}
                teamId={team.id}
                userId={userId}
                bookmarked={bookmarkedIds.has(post.papers.id)}
              />
            ))}
          </div>
        </Section>
      )}

      {!empty && (
        <Section
          title="Recently posted"
          action={{ label: "Browse all", onClick: () => navigate("/papers") }}
        >
          {search.isLoading ? (
            <ListSkeleton />
          ) : (
            <div className="divide-y divide-border overflow-hidden rounded-card border border-border shadow-sm">
              {recent.map((post) => (
                <PaperListRow
                  key={post.id}
                  post={post}
                  reactions={counts?.[post.papers.id]?.reactions ?? 0}
                  comments={counts?.[post.papers.id]?.comments ?? 0}
                  read={readIds?.has(post.papers.id)}
                  teamId={team.id}
                  userId={userId}
                  bookmarked={bookmarkedIds.has(post.papers.id)}
                  onOpen={() => openPaper(post.papers.id)}
                />
              ))}
            </div>
          )}
        </Section>
      )}
    </div>
  );
}

interface AttentionItem {
  key: string;
  accent: boolean;
  icon: ReactNode;
  lead: string;
  title: string;
  sub: string;
  onOpen: () => void;
  onClear: () => void;
}

function AttentionCard({ item }: { item: AttentionItem }) {
  return (
    <div className="flex items-start gap-3 rounded-card border border-border bg-surface p-3.5 shadow-sm transition hover:border-border-strong">
      <button onClick={item.onOpen} className="flex min-w-0 flex-1 items-start gap-3 text-left">
        <span
          className={cn(
            "grid h-8 w-8 shrink-0 place-items-center rounded-lg border",
            item.accent
              ? "border-accent/30 bg-accent-weak text-accent"
              : "border-border bg-surface-2 text-muted",
          )}
        >
          {item.icon}
        </span>
        <span className="min-w-0">
          <span className="block text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
            {item.lead}
          </span>
          <span className="mt-1 block text-sm font-semibold leading-snug">{item.title}</span>
          {item.sub && <span className="mt-1 block text-xs text-muted">{item.sub}</span>}
        </span>
      </button>
      <button
        onClick={item.onClear}
        title="Mark as read"
        aria-label="Mark as read"
        className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-faint transition hover:bg-surface-2 hover:text-fg"
      >
        <Check size={14} />
      </button>
    </div>
  );
}

/** Netflix-style scroll control overlaid on a horizontal row's edge. Appears on
 *  hover (pointer devices); touch users just swipe. */
function ScrollArrow({
  side,
  rowRef,
}: {
  side: "left" | "right";
  rowRef: RefObject<HTMLDivElement>;
}) {
  const Icon = side === "left" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      aria-label={side === "left" ? "Scroll left" : "Scroll right"}
      onClick={() =>
        rowRef.current?.scrollBy({ left: side === "left" ? -648 : 648, behavior: "smooth" })
      }
      className={cn(
        "absolute inset-y-0 z-10 hidden w-14 items-center opacity-0 transition group-hover/rec:opacity-100 md:flex",
        side === "left"
          ? "left-0 justify-start bg-gradient-to-r from-bg to-transparent"
          : "right-0 justify-end bg-gradient-to-l from-bg to-transparent",
      )}
    >
      <span className="grid h-8 w-8 place-items-center rounded-full border border-border bg-surface text-fg shadow-md transition hover:border-border-strong">
        <Icon size={16} />
      </span>
    </button>
  );
}

function Section({
  title,
  count,
  action,
  children,
}: {
  title: string;
  count?: number;
  action?: { label: string; onClick: () => void };
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-4 flex items-center gap-2.5">
        <h2 className="text-eyebrow font-bold uppercase tracking-eyebrow text-muted">{title}</h2>
        {count != null && <span className="text-xs tabular-nums text-muted">{count}</span>}
        {action && (
          <button
            onClick={action.onClick}
            className="ml-auto text-xs font-medium text-muted transition hover:text-accent"
          >
            {action.label} →
          </button>
        )}
      </div>
      {children}
    </section>
  );
}

function ListSkeleton() {
  return (
    <div className="divide-y divide-border overflow-hidden rounded-card border border-border">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3.5 px-4 py-3">
          <div className="h-9 w-14 shrink-0 animate-pulse rounded-md bg-surface-2" />
          <div className="flex-1">
            <div className="h-3.5 w-2/3 animate-pulse rounded bg-surface-2" />
            <div className="mt-1.5 h-2.5 w-1/3 animate-pulse rounded bg-surface-2" />
          </div>
        </div>
      ))}
    </div>
  );
}

function CardSkeleton() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="rounded-card border border-border bg-surface p-4 shadow-sm">
          <div className="h-24 w-full animate-pulse rounded-md bg-surface-2" />
          <div className="mt-3 h-3.5 w-3/4 animate-pulse rounded bg-surface-2" />
          <div className="mt-2 h-2.5 w-1/2 animate-pulse rounded bg-surface-2" />
        </div>
      ))}
    </div>
  );
}
