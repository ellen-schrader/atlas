import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookMarked, Check, CheckSquare, Loader2, Search, X } from "lucide-react";

import { ExportBar, SelectCheckbox } from "@/components/ExportBar";
import { usePaperModal } from "@/components/PaperModal";
import { useReadingList, useReadThisWeek } from "@/hooks/useReadingList";
import { isWakingRecommendations, useRecommendations } from "@/hooks/useRecommendations";
import { type Selection, useSelection } from "@/hooks/useSelection";
import type { ExportPaper } from "@/lib/paperExport";
import type { Progress } from "@/lib/paperStatus";
import { deleteIfDefault } from "@/lib/paperStatus";
import { supabase } from "@/lib/supabase";
import { cn, formatAuthors, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

type Sort = "recommended" | "added";

/** Which slice of the saved set is on screen. Membership never changes here —
 *  a paper leaves the saved set only by being un-saved — so this picks a view,
 *  not a filter on whether the paper is still yours. */
type View = "queue" | "read" | "all";

const VIEWS: { key: View; label: string; blurb: string }[] = [
  { key: "queue", label: "To read", blurb: "Saved and not started." },
  { key: "read", label: "Read", blurb: "Read and kept — still yours, still counting." },
  { key: "all", label: "All", blurb: "Everything you have saved." },
];

interface Item {
  paperId: string;
  title: string | null;
  authors: string[];
  venue: string | null;
  year: number | null;
  doi: string | null;
  url: string | null;
  abstract: string | null;
  added?: string; // when saved (updated_at) — present in "Date added" mode
  similarity?: number; // taste fit — present in "Recommended" mode
  status?: Progress; // reading progress — present in "Date added" mode
}

function itemToExport(it: Item): ExportPaper {
  return {
    id: it.paperId,
    title: it.title,
    authors: it.authors,
    venue: it.venue,
    year: it.year,
    doi: it.doi,
    url: it.url,
    abstract: it.abstract,
  };
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
  const [view, setView] = useState<View>("queue");
  const [sort, setSort] = useState<Sort>("added");
  const [query, setQuery] = useState("");
  const [venue, setVenue] = useState("");
  const selection = useSelection();

  const byDate = useReadingList(userId, team.id);
  const readWeek = useReadThisWeek(userId, team.id);
  // Only fetch (and, during a cold boot, poll) the ranked view when it's shown.
  const byRec = useRecommendations(team.id, "reading_list", 100, sort === "recommended");
  const recWaking = isWakingRecommendations(byRec);

  const items: Item[] =
    sort === "added"
      ? (byDate.data ?? []).map((r) => ({
          paperId: r.paper_id,
          title: r.papers?.title ?? null,
          authors: r.papers?.authors ?? [],
          venue: r.papers?.venue ?? null,
          year: r.papers?.year ?? null,
          doi: r.papers?.doi ?? null,
          url: r.papers?.url ?? null,
          abstract: r.papers?.abstract ?? null,
          added: r.updated_at,
          status: r.status,
        }))
      : (byRec.data?.results ?? []).map((r) => ({
          paperId: r.post.papers.id,
          title: r.post.papers.title ?? null,
          authors: r.post.papers.authors ?? [],
          venue: r.post.papers.venue ?? null,
          year: r.post.papers.year ?? null,
          doi: r.post.papers.doi ?? null,
          url: r.post.papers.url ?? null,
          abstract: r.post.papers.abstract ?? null,
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
  // "Recommended" ranks the whole saved set through the API and carries no
  // progress, so the view split only applies to the date-ordered read.
  const inView = (it: Item) =>
    view === "all" || !it.status
      ? true
      : view === "read"
        ? it.status === "read"
        : it.status !== "read";
  const shown = items.filter(
    (it) =>
      inView(it) &&
      (!venue || it.venue === venue) &&
      (!q ||
        (it.title ?? "").toLowerCase().includes(q) ||
        it.authors.some((a) => a.toLowerCase().includes(q))),
  );

  // Multi-select export acts on the currently-shown (filtered) papers.
  const shownIds = selection.selecting ? shown.map((it) => it.paperId) : [];
  const selectedPapers = selection.selecting
    ? shown.filter((it) => selection.isSelected(it.paperId)).map(itemToExport)
    : [];
  const allShownSelected = shownIds.length > 0 && shownIds.every((id) => selection.isSelected(id));

  // Reset the selection when the filters/sort change, so the count and "select all"
  // always match what's on screen and the export can't silently drop hidden picks.
  const { clear: clearSelection } = selection;
  useEffect(() => {
    clearSelection();
  }, [query, venue, sort, view, clearSelection]);

  // Canonical backlog size comes from the date view (always loaded), so the
  // header stays stable even while the ranked view is fetching.
  const saved = byDate.data ?? [];
  const total = saved.length;
  const queueCount = saved.filter((r) => r.status !== "read").length;
  const readCount = total - queueCount;
  const counts: Record<View, number> = { queue: queueCount, read: readCount, all: total };
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

  // Progress only. The paper stays saved, so it moves from "To read" into
  // "Read" rather than leaving the list — which is the point: a paper central to
  // your project should not disappear the moment you finish it.
  async function markRead(paperId: string, read = true) {
    await supabase
      .from("paper_status")
      .upsert(
        { user_id: userId, team_id: team.id, paper_id: paperId, status: read ? "read" : "unread" },
        { onConflict: "user_id,paper_id,team_id" },
      );
    await qc.invalidateQueries({ queryKey: ["reading-list"] });
    await qc.invalidateQueries({ queryKey: ["read-this-week"] });
    await qc.invalidateQueries({ queryKey: ["recommendations"] });
    await qc.invalidateQueries({ queryKey: ["read-papers"] });
  }

  // Membership only — the deliberate "this is not mine after all". Keeps any
  // reading progress, and drops the row entirely if nothing is left to say.
  async function removeFromList(paperId: string) {
    await supabase
      .from("paper_status")
      .update({ saved: false })
      .eq("user_id", userId)
      .eq("team_id", team.id)
      .eq("paper_id", paperId);
    await deleteIfDefault(supabase, userId, team.id, paperId);
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
              {queueCount > 0 ? (
                <>
                  {queueCount} to read · {readingTime(queueCount)}
                </>
              ) : (
                <span className="font-medium text-accent">Queue clear</span>
              )}
              {readCount > 0 && <> · {readCount} read and kept</>}
              {readWk > 0 && (
                <>
                  {" · "}
                  <span className="font-medium text-accent">{readWk} this week</span>
                </>
              )}
            </p>
          ) : (
            <p className="mt-1.5 text-sm text-muted">
              Papers you save in {team.name} land here — to read, and to keep.
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="flex rounded-control border border-border bg-surface p-0.5 text-sm">
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
          {total > 0 && (
            <button
              type="button"
              onClick={() => (selection.selecting ? selection.stop() : selection.start())}
              aria-pressed={selection.selecting}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-sm font-medium transition",
                selection.selecting
                  ? "border-accent/50 bg-accent-weak text-accent"
                  : "border-border text-muted hover:border-border-strong hover:text-fg",
              )}
            >
              <CheckSquare size={14} />
              Select
            </button>
          )}
        </div>
      </div>

      {total > 0 && (
        <div className="flex flex-col gap-1.5">
          <div
            // radiogroup, not tablist: these are three mutually exclusive
            // filters over one list, not three panels. A tablist promises
            // arrow-key navigation and an aria-controls'd tabpanel, neither of
            // which exists here — and the same control elsewhere in the app
            // (AddPaperDialog's ModeSwitch, the Cite format picker) is a
            // radiogroup already.
            role="radiogroup"
            aria-label="Which saved papers to show"
            className="flex gap-1 self-start rounded-control bg-surface-2 p-1"
          >
            {VIEWS.map((v) => (
              <button
                key={v.key}
                type="button"
                role="radio"
                aria-checked={view === v.key}
                onClick={() => setView(v.key)}
                className={cn(
                  "inline-flex items-center gap-2 rounded-control px-3 py-1.5 text-sm font-medium transition",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  view === v.key ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
                )}
              >
                {v.label}
                <span
                  className={cn(
                    "rounded-full px-1.5 py-0.5 text-xs tabular-nums",
                    view === v.key ? "bg-accent-weak text-accent" : "text-faint",
                  )}
                >
                  {counts[v.key]}
                </span>
              </button>
            ))}
          </div>
          <p className="text-xs text-faint">{VIEWS.find((v) => v.key === view)?.blurb}</p>
        </div>
      )}

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

      {/* An empty VIEW is not an empty search. Draining the queue is the whole
          point of the page, so it gets a result rather than "no matches". */}
      {!loading && !recError && items.length > 0 && shown.length === 0 && !filtering && (
        <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-border bg-surface-2 py-14 text-center">
          {view === "queue" ? (
            <>
              <Check size={22} className="text-accent" />
              <p className="text-sm font-medium">Queue clear</p>
              <p className="max-w-sm text-xs text-muted">
                Nothing left to read.{" "}
                {readCount > 0 && (
                  <button
                    onClick={() => setView("read")}
                    className="font-medium text-accent hover:underline"
                  >
                    {readCount} kept {readCount === 1 ? "paper" : "papers"}
                  </button>
                )}{" "}
                {readCount > 0 && "are still here."}
              </p>
            </>
          ) : (
            <>
              <BookMarked size={22} className="text-muted" />
              <p className="text-sm font-medium">Nothing read yet</p>
              <p className="max-w-sm text-xs text-muted">
                Papers you mark as read stay saved and move here.
              </p>
            </>
          )}
        </div>
      )}

      {!loading && !recError && items.length > 0 && shown.length === 0 && filtering && (
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
                  <ListCard
                    items={b.items}
                    onOpen={openPaper}
                    onMarkRead={markRead}
                    onRemove={removeFromList}
                    selection={selection}
                  />
                </section>
              ))}
            </div>
          ) : (
            <ListCard
              items={shown}
              onOpen={openPaper}
              onMarkRead={markRead}
              onRemove={removeFromList}
              selection={selection}
            />
          )}
        </>
      )}

      {/* Space so the floating export bar never hides the last row. */}
      {selection.selecting && <div aria-hidden className="h-16" />}

      {selection.selecting && (
        <ExportBar
          papers={selectedPapers}
          totalCount={shownIds.length}
          allSelected={allShownSelected}
          onSelectAll={() => selection.selectAll(shownIds)}
          onClear={selection.clear}
          onExit={selection.stop}
          heading="Reading list"
        />
      )}
    </div>
  );
}

function ListCard({
  items,
  onOpen,
  onMarkRead,
  onRemove,
  selection,
}: {
  items: Item[];
  onOpen: (id: string) => void;
  onMarkRead: (id: string, read: boolean) => void;
  onRemove: (id: string) => void;
  selection: Selection;
}) {
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-card border border-border shadow-sm">
      {items.map((it) => (
        <Row
          key={it.paperId}
          item={it}
          onOpen={onOpen}
          onMarkRead={onMarkRead}
          onRemove={onRemove}
          selection={selection}
        />
      ))}
    </ul>
  );
}

function Row({
  item,
  onOpen,
  onMarkRead,
  onRemove,
  selection,
}: {
  item: Item;
  onOpen: (id: string) => void;
  onMarkRead: (id: string, read: boolean) => void;
  onRemove: (id: string) => void;
  selection: Selection;
}) {
  const meta = [
    item.authors.length ? formatAuthors(item.authors, 1) : null,
    item.venue,
    item.year != null ? String(item.year) : null,
    item.added ? `added ${formatRelative(item.added)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const { selecting } = selection;
  const checked = selection.isSelected(item.paperId);

  return (
    <li
      className={cn(
        "group flex items-start gap-3 px-4 py-3 transition hover:bg-surface-2",
        selecting && checked && "bg-accent-weak",
      )}
    >
      {selecting && (
        <div className="pt-0.5">
          <SelectCheckbox checked={checked} onChange={() => selection.toggle(item.paperId)} />
        </div>
      )}

      <button
        onClick={() => (selecting ? selection.toggle(item.paperId) : onOpen(item.paperId))}
        className="min-w-0 flex-1 text-left"
      >
        <span className="block text-sm font-semibold leading-snug text-fg line-clamp-2">
          {item.title ?? "Untitled paper"}
        </span>
        <span className="mt-1 block truncate text-xs text-muted">{meta || "—"}</span>
      </button>

      {item.similarity != null && item.similarity > 0 && (
        <span className="mt-0.5 shrink-0 rounded-chip border border-accent/30 bg-accent-weak px-1.5 py-0.5 text-xs font-medium tabular-nums text-accent">
          {Math.round(item.similarity * 100)}% match
        </span>
      )}

      {/* In select mode the row's job is picking, not managing — hide the per-row
          actions so a tap can't accidentally mark-read or remove. */}
      {!selecting && (
        <div className="flex shrink-0 items-center gap-0.5 pt-0.5">
          <button
            onClick={() => onMarkRead(item.paperId, item.status !== "read")}
            title={item.status === "read" ? "Move back to “to read”" : "Mark as read"}
            aria-label={item.status === "read" ? "Mark as unread" : "Mark as read"}
            aria-pressed={item.status === "read"}
            className={cn(
              "grid h-7 w-7 place-items-center rounded-md transition hover:bg-surface-3",
              item.status === "read" ? "text-accent" : "text-faint hover:text-accent",
            )}
          >
            <Check size={15} />
          </button>
          <button
            onClick={() => onRemove(item.paperId)}
            title="Un-save — removes it from your list entirely"
            aria-label="Un-save this paper"
            className="grid h-7 w-7 place-items-center rounded-md text-faint transition hover:bg-surface-3 hover:text-danger"
          >
            <X size={15} />
          </button>
        </div>
      )}
    </li>
  );
}
