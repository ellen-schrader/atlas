import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { LayoutGrid, Plus, Rows3, Search } from "lucide-react";

import { Cover } from "@/components/Cover";
import { EngagementSummary } from "@/components/EngagementSummary";
import { PaperCard } from "@/components/PaperCard";
import { SourceLabel } from "@/components/SourceLabel";
import { usePaperModal } from "@/components/PaperModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useEngagementCounts } from "@/hooks/useEngagementCounts";
import { usePaperCount, usePaperSearch } from "@/hooks/usePaperSearch";
import { useReadingList } from "@/hooks/useReadingList";
import { useTeamTags } from "@/hooks/useTeamTags";
import { postPaper } from "@/lib/api";
import type { PaperPost } from "@/lib/types";
import { cn, formatAuthors, formatDate } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

export default function Papers() {
  const { team, userId } = useAppContext();
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 250);
  const [tag, setTag] = useState<string | null>(null);
  const [view, setView] = useState<"cards" | "table">("cards");
  const searchRef = useRef<HTMLInputElement>(null);

  // ⌘K / Ctrl-K focuses the search box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const search = usePaperSearch(team.id, query, tag);
  const { data: total } = usePaperCount(team.id, query, tag);
  const { data: tags } = useTeamTags(team.id);

  const posts = (search.data?.pages ?? []).flat();
  const { data: counts } = useEngagementCounts(
    team.id,
    posts.map((p) => p.papers.id),
  );
  const { data: reading } = useReadingList(userId, team.id);
  const bookmarked = new Set((reading ?? []).map((r) => r.paper_id));

  const { openPaper } = usePaperModal();

  // Infinite scroll: load the next page when the sentinel scrolls into view.
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && search.hasNextPage && !search.isFetchingNextPage) {
        void search.fetchNextPage();
      }
    });
    io.observe(el);
    return () => io.disconnect();
  }, [search.hasNextPage, search.isFetchingNextPage, search]);

  function clearFilters() {
    setRawQuery("");
    setTag(null);
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-display font-bold tracking-tight text-fg">Papers</h1>
          <p className="mt-1.5 text-sm text-muted">
            Everything shared in {team.name} — search, filter, and open to discuss.
          </p>
        </div>
      </div>

      <PostPaperBar teamId={team.id} />

      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] flex-1">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
          />
          <Input
            ref={searchRef}
            value={rawQuery}
            onChange={(e) => setRawQuery(e.target.value)}
            placeholder="Search title, author, abstract, tag…"
            className="pl-9 pr-12"
          />
          <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-border bg-surface-2 px-1.5 font-mono text-[11px] text-faint">
            ⌘K
          </kbd>
        </div>
        <div className="inline-flex overflow-hidden rounded-control border border-border">
          <ViewButton active={view === "cards"} onClick={() => setView("cards")} label="Card view">
            <LayoutGrid size={15} />
          </ViewButton>
          <ViewButton active={view === "table"} onClick={() => setView("table")} label="Table view">
            <Rows3 size={15} />
          </ViewButton>
        </div>
      </div>

      {/* tag filters */}
      <div className="-mt-1 flex flex-wrap gap-2">
        <FilterChip active={tag === null} onClick={() => setTag(null)}>
          All
        </FilterChip>
        {(tags ?? []).map((t) => (
          <FilterChip key={t.tag} active={tag === t.tag} onClick={() => setTag(t.tag)}>
            {t.tag}
          </FilterChip>
        ))}
      </div>

      {typeof total === "number" && !search.isLoading && (
        <div className="-mb-2 -mt-2 text-xs text-faint tabular-nums">
          {total} {total === 1 ? "paper" : "papers"}
          {(query || tag) && " match"}
        </div>
      )}

      {/* results */}
      {search.isLoading ? (
        <CardSkeletons />
      ) : search.isError ? (
        <ErrorState onRetry={() => search.refetch()} />
      ) : posts.length === 0 ? (
        <EmptyState filtered={Boolean(query || tag)} onClear={clearFilters} />
      ) : view === "cards" ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
          {posts.map((post) => (
            <PaperCard
              key={post.id}
              post={post}
              reactions={counts?.[post.papers.id]?.reactions ?? 0}
              comments={counts?.[post.papers.id]?.comments ?? 0}
              onOpen={() => openPaper(post.papers.id)}
              teamId={team.id}
              userId={userId}
              bookmarked={bookmarked.has(post.papers.id)}
            />
          ))}
        </div>
      ) : (
        <PaperTable posts={posts} counts={counts} onOpen={(id) => openPaper(id)} />
      )}

      {search.isFetchingNextPage && (
        <div className="py-4 text-center text-sm text-muted">Loading more…</div>
      )}
      <div ref={sentinel} aria-hidden className="h-px" />
    </div>
  );
}

function ViewButton({
  active,
  onClick,
  label,
  children,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "grid h-9 w-9 place-items-center transition",
        active ? "bg-surface-2 text-fg" : "text-muted hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-control border px-3 py-1.5 font-mono text-xs tracking-tight transition",
        active
          ? "border-accent/50 bg-accent-weak text-accent"
          : "border-border text-muted hover:border-border-strong hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

function PaperTable({
  posts,
  counts,
  onOpen,
}: {
  posts: PaperPost[];
  counts?: Record<string, { reactions: number; comments: number }>;
  onOpen: (paperId: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-card border border-border shadow-sm">
      <table className="w-full min-w-[680px] border-collapse text-sm">
        <thead>
          <tr className="bg-surface-2 text-left text-eyebrow uppercase tracking-eyebrow text-muted">
            <th className="px-4 py-2.5 font-semibold">Paper</th>
            <th className="px-4 py-2.5 font-semibold">Authors</th>
            <th className="px-4 py-2.5 font-semibold">Engagement</th>
            <th className="px-4 py-2.5 font-semibold">Posted</th>
          </tr>
        </thead>
        <tbody>
          {posts.map((post) => {
            const p = post.papers;
            const c = counts?.[p.id];
            return (
              <tr
                key={post.id}
                onClick={() => onOpen(p.id)}
                className="cursor-pointer border-t border-border align-middle transition hover:bg-surface-2"
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <span className="h-9 w-16 shrink-0 overflow-hidden rounded-md border border-border">
                      <Cover seed={p.id} />
                    </span>
                    <div className="min-w-0">
                      <div className="truncate font-medium text-fg">{p.title ?? p.url}</div>
                      <SourceLabel venue={p.venue} year={p.year} className="mt-0.5 block" />
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 text-muted">{formatAuthors(p.authors)}</td>
                <td className="px-4 py-3">
                  <EngagementSummary reactions={c?.reactions ?? 0} comments={c?.comments ?? 0} />
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-meta text-muted tabular-nums">
                  {formatDate(post.posted_at)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PostPaperBar({ teamId }: { teamId: string }) {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await postPaper(url.trim(), teamId);
      setMsg((r.already_posted ? "Already in your lab: " : "Posted: ") + (r.paper.title ?? r.paper.url));
      setUrl("");
      await qc.invalidateQueries({ queryKey: ["paper-search", teamId] });
      await qc.invalidateQueries({ queryKey: ["paper-count", teamId] });
      await qc.invalidateQueries({ queryKey: ["team-tags", teamId] });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Paste a paper URL — arXiv, DOI, PubMed, or a publisher page"
          required
        />
        <Button type="submit" disabled={busy || !url.trim()}>
          <Plus size={15} /> {busy ? "…" : "Post"}
        </Button>
      </div>
      {msg && <p className="text-xs text-muted">{msg}</p>}
      {error && <p className="text-xs text-danger">{error}</p>}
    </form>
  );
}

function CardSkeletons() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="h-[132px] w-full animate-pulse bg-surface-2" />
          <div className="flex flex-col gap-3 p-4">
            <div className="h-2.5 w-20 animate-pulse rounded bg-surface-2" />
            <div className="h-4 w-4/5 animate-pulse rounded bg-surface-2" />
            <div className="h-3 w-1/2 animate-pulse rounded bg-surface-2" />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ filtered, onClear }: { filtered: boolean; onClear: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-card border border-dashed border-border-strong px-6 py-16 text-center">
      <div className="font-semibold text-fg">
        {filtered ? "No papers match your filters" : "No papers yet"}
      </div>
      <p className="text-sm text-muted">
        {filtered ? "Try a different search term or clear the tag filter." : "Post one above to get started."}
      </p>
      {filtered && (
        <Button variant="secondary" size="sm" onClick={onClear}>
          Clear filters
        </Button>
      )}
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-card border border-dashed border-border-strong px-6 py-16 text-center">
      <div className="font-semibold text-fg">Couldn’t load papers</div>
      <p className="text-sm text-muted">Something went wrong fetching this lab’s papers.</p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}
