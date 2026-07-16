import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookMarked, Check, Loader2, Search, X } from "lucide-react";

import { usePaperModal } from "@/components/PaperModal";
import { useReadingList, useReadThisWeek } from "@/hooks/useReadingList";
import { isWakingRecommendations, useRecommendations } from "@/hooks/useRecommendations";
import { supabase } from "@/lib/supabase";
import { cn, formatAuthors, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

type Sort = "recommended" | "added";

interface Item {
  paperId: string;
  title: string;
  authors: string[];
  venue: string | null;
  year: number | null;
  added?: string; // when saved (updated_at) — present in "Date added" mode
  similarity?: number; // taste fit — present in "Recommended" mode
}

// A rough "engaged skim" per paper, so the header can size the backlog in time.
const MIN_PER_PAPER = 20;
function readingTime(n: number): string {
  const min = n * MIN_PER_PAPER;
  return min < 90 ? `~${min}m` : `~${Math.round(min / 60)}h`;
}

// Bucket a save time into the queue's recency bands, so a long list gets rhythm
// and stale items are visible rather than buried.
function bucketOf(iso: string): "today" | "week" | "earlier" {
  const t = new Date(iso).getTime();
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  if (t >= startOfToday.getTime()) return "today";
  if (t >= Date.now() - 7 * 24 * 60 * 60 * 1000) return "week";
  return "earlier";
}
const BANDS: { key: "today" | "week" | "earlier"; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "week", label: "This week" },
  { key: "earlier", label: "Earlier" },
];

/** The user's saved (to-read) papers as a working queue: scaled and grouped by
 *  when they were saved, or ranked by taste fit, and searchable/filterable once
 *  the list grows. "Date added" is a pure Supabase read (works offline);
 *  "Recommended" ranks the same papers via the API. */
export default function ReadingList() {
  const { team, userId } = useAppContext();
  const { openPaper } = usePaperModal();
  const qc = useQueryClient();
  const [sort, setSort] = useState<Sort>("added");
  const [query, setQuery] = useState("");
  const [venue, setVenue] = useState("");

  const byDate = useReadingList(userId, team.id);
  const readWeek = useReadThisWeek(userId, team.id);
  // Only fetch (and, during a cold boot, poll) the ranked view when it's shown.
  const byRec = useRecommendations(team.id, "reading_list", 100, sort === "recommended");
  const recWaking = isWakingRecommendations(byRec);

  const items: Item[] =
    sort === "added"
      ? (byDate.data ?? []).map((r) => ({
          paperId: r.paper_id,
          title: r.papers?.title ?? "Untitled paper",
          authors: r.papers?.authors ?? [],
          venue: r.papers?.venue ?? null,
          year: r.papers?.year ?? null,
          added: r.updated_at,
        }))
      : (byRec.data?.results ?? []).map((r) => ({
          paperId: r.post.papers.id,
          title: r.post.papers.title ?? "Untitled paper",
          authors: r.post.papers.authors ?? [],
          venue: r.post.papers.venue ?? null,
          year: r.post.papers.year ?? null,
          similarity: r.similarity,
        }));

  const loading = sort === "added" ? byDate.isLoading : byRec.isLoading;
  const recError = sort === "recommended" && byRec.isError;
  const empty = !loading && !recError && items.length === 0;

  // Venue options come from the whole saved list (not the filtered view), so the
  // menu is stable, and each option carries its count.
  const venues = Object.entries(
    (byDate.data ?? []).reduce<Record<string, number>>((m, r) => {
      const v = r.papers?.venue;
      if (v) m[v] = (m[v] ?? 0) + 1;
      return m;
    }, {}),
  ).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

  const q = query.trim().toLowerCase();
  const filtering = Boolean(q || venue);
  const shown = items.filter(
    (it) =>
      (!venue || it.venue === venue) &&
      (!q ||
        it.title.toLowerCase().includes(q) ||
        it.authors.some((a) => a.toLowerCase().includes(q))),
  );

  // Canonical backlog size comes from the date view (always loaded), so the
  // header stays stable even while the ranked view is fetching.
  const total = byDate.data?.length ?? 0;
  const readWk = readWeek.data ?? 0;

  // "Date added" reads as a queue when grouped by recency; "Recommended" is a
  // single ranked run, so it stays flat.
  const bands =
    sort === "added"
      ? BANDS.map((b) => ({ ...b, items: shown.filter((i) => i.added && bucketOf(i.added) === b.key) })).filter(
          (b) => b.items.length > 0,
        )
      : null;

  function clearFilters() {
    setQuery("");
    setVenue("");
  }

  async function markRead(paperId: string) {
    await supabase
      .from("paper_status")
      .upsert(
        { user_id: userId, team_id: team.id, paper_id: paperId, status: "read" },
        { onConflict: "user_id,paper_id,team_id" },
      );
    await qc.invalidateQueries({ queryKey: ["reading-list"] });
    await qc.invalidateQueries({ queryKey: ["read-this-week"] });
    await qc.invalidateQueries({ queryKey: ["recommendations"] });
    await qc.invalidateQueries({ queryKey: ["read-papers"] });
  }

  async function removeFromList(paperId: string) {
    await supabase
      .from("paper_status")
      .delete()
      .eq("user_id", userId)
      .eq("team_id", team.id)
      .eq("paper_id", paperId)
      .eq("status", "to_read");
    await qc.invalidateQueries({ queryKey: ["reading-list"] });
    await qc.invalidateQueries({ queryKey: ["recommendations"] });
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-display font-serif font-semibold tracking-tight">Reading list</h1>
          {total > 0 ? (
            <p className="mt-1.5 text-sm text-muted">
              {total} paper{total === 1 ? "" : "s"} · {readingTime(total)} to read
              {readWk > 0 && (
                <>
                  {" · "}
                  <span className="font-medium text-accent">{readWk} read this week</span>
                </>
              )}
            </p>
          ) : (
            <p className="mt-1.5 text-sm text-muted">Papers you saved to read in {team.name}.</p>
          )}
        </div>
        <div className="flex shrink-0 rounded-control border border-border bg-surface p-0.5 text-sm">
          {(["recommended", "added"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSort(s)}
              className={cn(
                "rounded-[7px] px-3 py-1.5 font-medium transition",
                sort === s ? "bg-accent-weak text-accent" : "text-muted hover:text-fg",
              )}
            >
              {s === "recommended" ? "Recommended" : "Date added"}
            </button>
          ))}
        </div>
      </div>

      {total > 0 && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="flex flex-1 items-center gap-2 rounded-control border border-border bg-surface-2 px-2.5 py-1.5">
            <Search size={14} className="shrink-0 text-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search title or author…"
              aria-label="Search reading list by title or author"
              className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-faint"
            />
            {query && (
              <button type="button" onClick={() => setQuery("")} aria-label="Clear search">
                <X size={13} className="text-muted hover:text-fg" />
              </button>
            )}
          </div>
          {venues.length > 1 && (
            <select
              value={venue}
              onChange={(e) => setVenue(e.target.value)}
              aria-label="Filter by venue"
              className="rounded-control border border-border bg-surface px-2.5 py-1.5 text-sm text-fg transition hover:border-border-strong focus:border-accent focus:outline-none"
            >
              <option value="">All venues</option>
              {venues.map(([v, c]) => (
                <option key={v} value={v}>
                  {v} ({c})
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16 text-muted">
          <Loader2 className="animate-spin" size={20} />
        </div>
      )}

      {recError && (
        <div className="rounded-card border border-dashed border-border bg-surface-2 p-5 text-sm">
          <p className="font-medium">
            {recWaking ? "Waking the paper service…" : "Couldn’t rank by recommendation right now."}
          </p>
          <p className="mt-1 text-xs text-muted">
            {recWaking ? (
              <>The ranking will appear here shortly, or </>
            ) : (
              <>The recommendation service isn’t reachable — </>
            )}
            <button onClick={() => setSort("added")} className="font-medium text-accent hover:underline">
              sort by date added
            </button>{" "}
            instead.
          </p>
        </div>
      )}

      {empty && (
        <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-border bg-surface-2 py-16 text-center">
          <BookMarked size={22} className="text-muted" />
          <p className="text-sm font-medium">Your reading list is empty</p>
          <p className="max-w-sm text-xs text-muted">
            Bookmark papers from the Papers page or a paper’s detail view and they’ll collect here.
          </p>
        </div>
      )}

      {!loading && !recError && items.length > 0 && shown.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-border bg-surface-2 py-14 text-center">
          <p className="text-sm font-medium">No papers match your filters</p>
          <button onClick={clearFilters} className="text-xs font-medium text-accent hover:underline">
            Clear filters
          </button>
        </div>
      )}

      {!loading && !recError && shown.length > 0 && (
        <>
          {filtering && (
            <p className="-mt-2 text-xs text-faint">
              {shown.length} of {items.length} shown
              <button onClick={clearFilters} className="ml-2 font-medium text-accent hover:underline">
                Clear
              </button>
            </p>
          )}
          {bands ? (
            <div className="flex flex-col gap-6">
              {bands.map((b) => (
                <section key={b.key}>
                  <h2 className="mb-2 flex items-baseline gap-2 text-xs font-semibold uppercase tracking-wide text-faint">
                    {b.label}
                    <span className="tabular-nums text-muted/60">{b.items.length}</span>
                  </h2>
                  <ListCard items={b.items} onOpen={openPaper} onMarkRead={markRead} onRemove={removeFromList} />
                </section>
              ))}
            </div>
          ) : (
            <ListCard items={shown} onOpen={openPaper} onMarkRead={markRead} onRemove={removeFromList} />
          )}
        </>
      )}
    </div>
  );
}

function ListCard({
  items,
  onOpen,
  onMarkRead,
  onRemove,
}: {
  items: Item[];
  onOpen: (id: string) => void;
  onMarkRead: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-card border border-border shadow-sm">
      {items.map((it) => (
        <Row key={it.paperId} item={it} onOpen={onOpen} onMarkRead={onMarkRead} onRemove={onRemove} />
      ))}
    </ul>
  );
}

function Row({
  item,
  onOpen,
  onMarkRead,
  onRemove,
}: {
  item: Item;
  onOpen: (id: string) => void;
  onMarkRead: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const meta = [
    item.authors.length ? formatAuthors(item.authors, 1) : null,
    item.venue,
    item.year != null ? String(item.year) : null,
    item.added ? `added ${formatRelative(item.added)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className="group flex items-start gap-3 px-4 py-3 transition hover:bg-surface-2">
      <button onClick={() => onOpen(item.paperId)} className="min-w-0 flex-1 text-left">
        <span className="block text-sm font-semibold leading-snug text-fg line-clamp-2">{item.title}</span>
        <span className="mt-1 block truncate text-xs text-muted">{meta || "—"}</span>
      </button>

      {item.similarity != null && item.similarity > 0 && (
        <span className="mt-0.5 shrink-0 rounded-chip border border-accent/30 bg-accent-weak px-1.5 py-0.5 text-xs font-medium tabular-nums text-accent">
          {Math.round(item.similarity * 100)}% match
        </span>
      )}

      <div className="flex shrink-0 items-center gap-0.5 pt-0.5">
        <button
          onClick={() => onMarkRead(item.paperId)}
          title="Mark as read"
          aria-label="Mark as read"
          className="grid h-7 w-7 place-items-center rounded-md text-faint transition hover:bg-surface-3 hover:text-accent"
        >
          <Check size={15} />
        </button>
        <button
          onClick={() => onRemove(item.paperId)}
          title="Remove from reading list"
          aria-label="Remove from reading list"
          className="grid h-7 w-7 place-items-center rounded-md text-faint transition hover:bg-surface-3 hover:text-danger"
        >
          <X size={15} />
        </button>
      </div>
    </li>
  );
}
