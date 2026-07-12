import { type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { AtSign, Bookmark, Check } from "lucide-react";

import { InviteCode } from "@/components/InviteCode";
import { PaperCard } from "@/components/PaperCard";
import { PaperListRow } from "@/components/PaperListRow";
import { usePaperModal } from "@/components/PaperModal";
import { useEngagementCounts } from "@/hooks/useEngagementCounts";
import { useMentionActions } from "@/hooks/useMentionActions";
import { useMentions } from "@/hooks/useMentions";
import { usePaperSearch } from "@/hooks/usePaperSearch";
import { useReadingList } from "@/hooks/useReadingList";
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

  const search = usePaperSearch(team.id, "", null);
  const posts = (search.data?.pages ?? []).flat();
  const { data: counts } = useEngagementCounts(
    team.id,
    posts.map((p) => p.papers.id),
  );
  const { data: mentions } = useMentions(userId);
  const { data: toRead } = useReadingList(userId, team.id);
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
        <h1 className="text-display font-bold tracking-tight">
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
