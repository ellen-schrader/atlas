import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LayoutGrid, ListFilter, Plus, Rows3, Search, Sparkles, X } from "lucide-react";

import { AddPaperDialog } from "@/components/AddPaperDialog";
import { BookmarkButton } from "@/components/BookmarkButton";
import { EngagementSummary } from "@/components/EngagementSummary";
import { SelectCheckbox, SelectionExportBar, SelectToggle } from "@/components/ExportBar";
import { PaperCard } from "@/components/PaperCard";
import { SourceLabel } from "@/components/SourceLabel";
import { usePaperModal } from "@/components/PaperModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useDismiss } from "@/hooks/useDismiss";
import { useEngagementCounts } from "@/hooks/useEngagementCounts";
import { useSelection } from "@/hooks/useSelection";
import {
  activeFilterCount,
  NO_FILTERS,
  type PaperFilters,
  type PaperSort,
  type PaperStatus,
  usePaperCount,
  usePaperSearch,
} from "@/hooks/usePaperSearch";
import { useReadingList } from "@/hooks/useReadingList";
import { useReadPapers } from "@/hooks/useReadPapers";
import { type TagCount, useTeamTags } from "@/hooks/useTeamTags";
import { type VenueCount, useTeamVenues } from "@/hooks/useTeamVenues";
import { semanticSearch } from "@/lib/api";
import type { ExportPaper } from "@/lib/paperExport";
import type { PaperPost } from "@/lib/types";
import { cn, formatAuthors, formatDate, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/** A shared paper (with its full canonical record) as an exportable row. */
function postToExport(post: PaperPost): ExportPaper {
  const p = post.papers;
  return {
    id: p.id,
    title: p.title,
    authors: p.authors ?? [],
    venue: p.venue,
    year: p.year,
    doi: p.doi,
    url: p.url,
    abstract: p.abstract,
  };
}

type SearchMode = "keyword" | "semantic";

/** The card grid: container-aware, so it accounts for the sidebar automatically.
 *  A 300px min track is what makes three columns fit the page's content box
 *  (max-w-5xl minus p-8 = 960px; 3×300 + 2×16 gap = 932 ≤ 960), while still
 *  falling back to 2 and 1 columns — never below 300px — as space shrinks.
 *  Shared with CardSkeletons so the skeleton can't drift from the real layout. */
const CARD_GRID = "grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4";

const STATUS_LABEL: Record<PaperStatus, string> = {
  unread: "Unread",
  to_read: "Saved to read",
  reading: "Reading",
  read: "Read",
};

const SORT_LABEL: Record<PaperSort, string> = {
  shared: "Recently shared",
  published: "Recently published",
};

export default function Papers() {
  const { team, userId } = useAppContext();
  const [mode, setMode] = useState<SearchMode>("keyword");
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 250);
  const [semanticQuery, setSemanticQuery] = useState("");
  const [filters, setFilters] = useState<PaperFilters>(NO_FILTERS);
  const [view, setView] = useState<"cards" | "table">("cards");
  const [sort, setSort] = useState<PaperSort>("shared");
  const [adding, setAdding] = useState(false);
  const selection = useSelection();
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

  // Keyword: live, server-side, paginated full-text search.
  // Semantic results come from a different query and ignore these filters, so don't
  // fetch with them — and don't let a filter set in keyword mode silently persist.
  const activeFilters = mode === "keyword" ? filters : NO_FILTERS;
  const search = usePaperSearch(team.id, mode === "keyword" ? query : "", activeFilters, sort);
  const { data: total } = usePaperCount(team.id, query, activeFilters);
  const { data: tags } = useTeamTags(team.id);
  const { data: venues } = useTeamVenues(team.id);

  // Semantic: runs on submit (each search embeds the query), so it isn't live.
  const semantic = useQuery({
    queryKey: ["semantic-search", team.id, semanticQuery],
    enabled: mode === "semantic" && semanticQuery.length > 0,
    queryFn: () => semanticSearch(semanticQuery, team.id),
  });

  const posts =
    mode === "semantic"
      ? (semantic.data ?? []).map((h) => h.post)
      : (search.data?.pages ?? []).flat();

  const { data: counts } = useEngagementCounts(
    team.id,
    posts.map((p) => p.papers.id),
  );
  const { data: reading } = useReadingList(userId, team.id);
  const { data: readIds } = useReadPapers(userId, team.id);
  const bookmarked = new Set((reading ?? []).map((r) => r.paper_id));

  const { openPaper } = usePaperModal();

  // Changing what the list shows changes what "select all" and the count refer to,
  // so reset the selection when the query/filters/sort/mode change — otherwise
  // picks that leave the view would be silently dropped from the export.
  const { clear: clearSelection } = selection;
  useEffect(() => {
    clearSelection();
  }, [query, filters, sort, mode, clearSelection]);

  // Infinite scroll (keyword only; semantic returns a ranked top-N).
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (mode !== "keyword") return;
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && search.hasNextPage && !search.isFetchingNextPage) {
        void search.fetchNextPage();
      }
    });
    io.observe(el);
    return () => io.disconnect();
  }, [mode, search.hasNextPage, search.isFetchingNextPage, search]);

  const nFilters = activeFilterCount(filters);

  function clearAll() {
    setRawQuery("");
    setFilters(NO_FILTERS);
    setSemanticQuery("");
    setMode("keyword");
  }

  /** Re-run the current query by meaning. Semantic search is a *refinement* of a
   *  search you already typed, not a mode you must pick before typing — which is
   *  what the old two-button toggle forced you to do. */
  function searchByMeaning() {
    const q = rawQuery.trim();
    if (!q) return;
    setFilters(NO_FILTERS);
    setMode("semantic");
    setSemanticQuery(q);
  }

  function backToKeyword() {
    setMode("keyword");
    setSemanticQuery("");
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    // In semantic mode Enter re-runs the (re-embedded) query; in keyword mode the
    // list is already live, so Enter is a no-op that shouldn't reload the page.
    if (mode === "semantic") setSemanticQuery(rawQuery.trim());
  }

  // Which results view to show.
  const state: "loading" | "error" | "empty" | "results" =
    mode === "semantic"
      ? semantic.isFetching
        ? "loading"
        : semantic.isError
          ? "error"
          : posts.length === 0
            ? "empty"
            : "results"
      : search.isLoading
        ? "loading"
        : search.isError
          ? "error"
          : posts.length === 0
            ? "empty"
            : "results";

  const narrowed = Boolean(query || nFilters > 0 || mode === "semantic");

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 p-8">
      {/* Header. Adding a paper is the one *write* action on this page, so it gets
          the one primary button — instead of a permanent form parked above the list. */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-display font-serif font-semibold tracking-tight text-fg">Papers</h1>
          <p className="mt-1.5 text-sm text-muted">
            Everything shared in {team.name} — search, filter, and open to discuss.
          </p>
        </div>
        <Button onClick={() => setAdding(true)} className="shrink-0">
          <Plus size={15} /> Add paper
        </Button>
      </div>

      {/* One toolbar row: search, filters, sort, view. Everything that was a
          permanently-expanded control is now a menu that opens when asked. */}
      <div className="flex flex-wrap items-center gap-2">
        <form onSubmit={onSubmit} className="relative min-w-[240px] flex-1">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
          />
          <Input
            ref={searchRef}
            value={rawQuery}
            onChange={(e) => {
              setRawQuery(e.target.value);
              // Typing again after a semantic search means a new search, not a
              // stale ranked list sitting under a changed query.
              if (mode === "semantic") backToKeyword();
            }}
            placeholder="Search papers by title, author, abstract, or tag…"
            className="pl-9 pr-12"
          />
          {rawQuery ? (
            <button
              type="button"
              onClick={() => {
                setRawQuery("");
                backToKeyword();
                searchRef.current?.focus();
              }}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded text-faint hover:text-fg"
            >
              <X size={14} />
            </button>
          ) : (
            <kbd className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-border bg-surface-2 px-1.5 font-mono text-[11px] text-faint pointer-fine:block">
              ⌘K
            </kbd>
          )}
        </form>

        <FilterMenu
          filters={filters}
          setFilters={setFilters}
          tags={tags ?? []}
          venues={venues ?? []}
          disabled={mode === "semantic"}
        />

        <Menu
          label={SORT_LABEL[sort]}
          title="Sort"
          disabled={mode === "semantic"}
          width="w-56"
        >
          {(close) => (
            <>
              <MenuTitle>Sort by</MenuTitle>
              {(Object.keys(SORT_LABEL) as PaperSort[]).map((s) => (
                <MenuOption
                  key={s}
                  selected={sort === s}
                  onClick={() => {
                    setSort(s);
                    close();
                  }}
                >
                  {SORT_LABEL[s]}
                </MenuOption>
              ))}
            </>
          )}
        </Menu>

        <div className="inline-flex overflow-hidden rounded-control border border-border">
          <ViewButton active={view === "cards"} onClick={() => setView("cards")} label="Card view">
            <LayoutGrid size={15} />
          </ViewButton>
          <ViewButton active={view === "table"} onClick={() => setView("table")} label="Table view">
            <Rows3 size={15} />
          </ViewButton>
        </div>

        {/* Enter multi-select to copy or export a set of papers. */}
        <SelectToggle selection={selection} className="h-9 shrink-0" />
      </div>

      {/* What's on screen, and how to undo it. Active filters are chips *here*,
          where they describe the result — not a wall of every tag in the lab. */}
      <div className="flex min-h-[26px] flex-wrap items-center gap-x-3 gap-y-2">
        <ResultCount
          mode={mode}
          loading={state === "loading"}
          total={total}
          shown={posts.length}
          narrowed={narrowed}
        />

        {mode === "keyword" &&
          (Object.keys(filters) as (keyof PaperFilters)[])
            .filter((k) => filters[k])
            .map((k) => (
              <ActiveChip
                key={k}
                onRemove={() => setFilters((f) => ({ ...f, [k]: null }))}
              >
                {k === "status" ? STATUS_LABEL[filters.status as PaperStatus] : filters[k]}
              </ActiveChip>
            ))}

        {mode === "semantic" && (
          <ActiveChip onRemove={backToKeyword} tone="accent">
            <Sparkles size={11} className="mr-1 inline" />
            Ranked by meaning
          </ActiveChip>
        )}

        {/* The escape hatch from semantic search's biggest weakness: it can't do
            exact strings. And the way in — offered once you've typed, so nobody has
            to know what "semantic" means before they can search at all. */}
        {mode === "keyword" && rawQuery.trim() && (
          <button
            type="button"
            onClick={searchByMeaning}
            className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
          >
            <Sparkles size={12} /> Search by meaning instead
          </button>
        )}

        {narrowed && (
          <button
            type="button"
            onClick={clearAll}
            className="ml-auto text-xs font-medium text-muted underline underline-offset-2 hover:text-fg"
          >
            Reset
          </button>
        )}
      </div>

      {/* results */}
      {state === "loading" ? (
        <CardSkeletons />
      ) : state === "error" ? (
        <ErrorState onRetry={() => (mode === "semantic" ? semantic.refetch() : search.refetch())} />
      ) : state === "empty" ? (
        <EmptyState
          mode={mode}
          narrowed={narrowed}
          onClear={clearAll}
          onAdd={() => setAdding(true)}
        />
      ) : view === "cards" ? (
        <div className={CARD_GRID}>
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
              // Undefined while the query is in flight — `?? false` would claim every
              // card is unread for a frame, which is the one thing the dot mustn't do.
              read={readIds ? readIds.has(post.papers.id) : undefined}
              selecting={selection.selecting}
              selected={selection.isSelected(post.papers.id)}
              onToggleSelect={() => selection.toggle(post.papers.id)}
            />
          ))}
        </div>
      ) : (
        <PaperTable
          posts={posts}
          counts={counts}
          readIds={readIds}
          teamId={team.id}
          userId={userId}
          bookmarked={bookmarked}
          onOpen={(id) => openPaper(id)}
          selecting={selection.selecting}
          isSelected={selection.isSelected}
          onToggleSelect={selection.toggle}
        />
      )}

      {mode === "keyword" && search.isFetchingNextPage && (
        <div className="py-4 text-center text-sm text-muted">Loading more…</div>
      )}
      <div ref={sentinel} aria-hidden className="h-px" />

      <SelectionExportBar
        selection={selection}
        items={posts}
        idOf={(post) => post.papers.id}
        toExport={postToExport}
        heading={team.name}
      />

      <AddPaperDialog
        open={adding}
        onClose={() => setAdding(false)}
        teamId={team.id}
        onAdded={(paperId) => {
          setAdding(false);
          openPaper(paperId);
        }}
      />
    </div>
  );
}

/** "55 papers" / "12 of 55" / "18 by relevance" — one line that always says what
 *  the list below actually is. */
function ResultCount({
  mode,
  loading,
  total,
  shown,
  narrowed,
}: {
  mode: SearchMode;
  loading: boolean;
  total?: number;
  shown: number;
  narrowed: boolean;
}) {
  if (loading) return <span className="text-xs text-faint">Searching…</span>;
  if (mode === "semantic") {
    return (
      <span className="text-xs text-faint tabular-nums">
        {shown} {shown === 1 ? "paper" : "papers"} by relevance
      </span>
    );
  }
  if (typeof total !== "number") return null;
  return (
    <span className="text-xs text-faint tabular-nums">
      {total} {total === 1 ? "paper" : "papers"}
      {narrowed && " match"}
    </span>
  );
}

/** Status + venue + tag, behind one button with a count. Three always-visible
 *  controls (two of which could list 30 venues and every tag in the lab) is the
 *  single biggest source of noise on this page. */
function FilterMenu({
  filters,
  setFilters,
  tags,
  venues,
  disabled,
}: {
  filters: PaperFilters;
  setFilters: (fn: (f: PaperFilters) => PaperFilters) => void;
  tags: TagCount[];
  venues: VenueCount[];
  disabled?: boolean;
}) {
  const n = activeFilterCount(filters);
  return (
    <Menu
      title="Filters"
      disabled={disabled}
      width="w-72"
      active={n > 0}
      label={
        <>
          <ListFilter size={14} />
          Filters
          {n > 0 && (
            <span className="ml-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-fg tabular-nums">
              {n}
            </span>
          )}
        </>
      }
    >
      {() => (
        <div className="flex flex-col gap-3 p-3">
          <FilterSelect
            label="Your reading status"
            value={filters.status ?? ""}
            onChange={(v) => setFilters((f) => ({ ...f, status: (v || null) as PaperStatus | null }))}
            options={[
              { value: "", label: "Any status" },
              ...(Object.keys(STATUS_LABEL) as PaperStatus[]).map((s) => ({
                value: s,
                label: STATUS_LABEL[s],
              })),
            ]}
          />
          <FilterSelect
            label="Venue"
            value={filters.venue ?? ""}
            onChange={(v) => setFilters((f) => ({ ...f, venue: v || null }))}
            options={[
              { value: "", label: "Any venue" },
              ...venues.map((v) => ({ value: v.venue, label: `${v.venue} (${v.count})` })),
              // team_venues caps at 30. Say so, rather than let the menu imply these
              // are all the venues the lab has.
              ...(venues.length >= 30
                ? [{ value: "", label: "— top 30 venues shown —", disabled: true }]
                : []),
            ]}
          />
          <FilterSelect
            label="Tag"
            value={filters.tag ?? ""}
            onChange={(v) => setFilters((f) => ({ ...f, tag: v || null }))}
            options={[
              { value: "", label: "Any tag" },
              ...tags.map((t) => ({ value: t.tag, label: `${t.tag} (${t.n})` })),
            ]}
          />
          {n > 0 && (
            <button
              type="button"
              onClick={() => setFilters(() => NO_FILTERS)}
              className="self-start text-xs font-medium text-muted underline underline-offset-2 hover:text-fg"
            >
              Clear {n} {n === 1 ? "filter" : "filters"}
            </button>
          )}
        </div>
      )}
    </Menu>
  );
}

/** A button that opens a panel below it. Closes on Escape, on a click outside, and
 *  on choosing something. */
function Menu({
  label,
  title,
  width,
  active,
  disabled,
  children,
}: {
  label: ReactNode;
  title: string;
  width: string;
  active?: boolean;
  disabled?: boolean;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useDismiss(ref, open, () => setOpen(false));

  // A disabled control that stays open would float over results it can't affect.
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        title={title}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex h-9 items-center gap-1.5 rounded-control border px-3 text-sm font-medium transition",
          "disabled:cursor-not-allowed disabled:opacity-40",
          active
            ? "border-accent/50 bg-accent-weak text-accent"
            : "border-border text-muted hover:border-border-strong hover:text-fg",
        )}
      >
        {label}
      </button>
      {open && (
        <div
          className={cn(
            "absolute right-0 top-full z-30 mt-1.5 overflow-hidden rounded-card border border-border bg-surface shadow-xl",
            width,
          )}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

function MenuTitle({ children }: { children: ReactNode }) {
  return (
    <div className="px-3 pb-1 pt-2.5 text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
      {children}
    </div>
  );
}

function MenuOption({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center justify-between px-3 py-2 text-left text-sm transition hover:bg-surface-2",
        selected ? "font-medium text-accent" : "text-fg",
      )}
    >
      {children}
      {selected && <span aria-hidden>✓</span>}
    </button>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string; disabled?: boolean }[];
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-control border border-border bg-surface px-2 py-1.5 text-sm text-fg transition hover:border-border-strong focus:border-accent focus:outline-none"
      >
        {options.map((o, i) => (
          <option key={`${o.value}-${i}`} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function ActiveChip({
  children,
  onRemove,
  tone = "default",
}: {
  children: ReactNode;
  onRemove: () => void;
  tone?: "default" | "accent";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-chip border px-2 py-0.5 text-xs font-medium",
        tone === "accent"
          ? "border-accent/50 bg-accent-weak text-accent"
          : "border-border bg-surface-2 text-muted",
      )}
    >
      {children}
      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove filter"
        className="-mr-0.5 grid h-4 w-4 place-items-center rounded-full hover:bg-black/10"
      >
        <X size={11} />
      </button>
    </span>
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

function PaperTable({
  posts,
  counts,
  readIds,
  teamId,
  userId,
  bookmarked,
  onOpen,
  selecting = false,
  isSelected,
  onToggleSelect,
}: {
  posts: PaperPost[];
  counts?: Record<string, { reactions: number; comments: number }>;
  readIds?: Set<string>;
  onOpen: (paperId: string) => void;
  teamId: string;
  userId: string;
  bookmarked: Set<string>;
  selecting?: boolean;
  isSelected?: (id: string) => boolean;
  onToggleSelect?: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-card border border-border shadow-sm">
      <table className="w-full min-w-[680px] border-collapse text-sm">
        <thead>
          <tr className="bg-surface-2 text-left text-eyebrow uppercase tracking-eyebrow text-muted">
            {selecting && (
              <th className="w-10 px-4 py-2.5 font-semibold">
                <span className="sr-only">Select</span>
              </th>
            )}
            <th className="px-4 py-2.5 font-semibold">Paper</th>
            <th className="px-4 py-2.5 font-semibold">Authors</th>
            <th className="px-4 py-2.5 font-semibold">Engagement</th>
            <th className="px-4 py-2.5 font-semibold">Posted</th>
            <th className="px-4 py-2.5 font-semibold">
              <span className="sr-only">Save</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {posts.map((post) => {
            const p = post.papers;
            const c = counts?.[p.id];
            const read = readIds?.has(p.id) ?? false;
            const checked = isSelected?.(p.id) ?? false;
            return (
              <tr
                key={post.id}
                onClick={() => (selecting ? onToggleSelect?.(p.id) : onOpen(p.id))}
                className={cn(
                  "cursor-pointer border-t border-border align-middle transition hover:bg-surface-2",
                  selecting && checked && "bg-accent-weak",
                )}
              >
                {selecting && (
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <SelectCheckbox checked={checked} onChange={() => onToggleSelect?.(p.id)} />
                  </td>
                )}
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <span
                      aria-label={read ? undefined : "Unread"}
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        read ? "bg-transparent" : "bg-accent",
                      )}
                    />
                    <div className="min-w-0">
                      <div className={cn("truncate", read ? "text-muted" : "font-medium text-fg")}>
                        {p.title ?? p.url}
                      </div>
                      <SourceLabel venue={p.venue} year={p.year} className="mt-0.5 block" />
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 text-muted">{formatAuthors(p.authors)}</td>
                <td className="px-4 py-3">
                  <EngagementSummary reactions={c?.reactions ?? 0} comments={c?.comments ?? 0} />
                </td>
                <td
                  className="whitespace-nowrap px-4 py-3 text-meta text-muted tabular-nums"
                  title={formatDate(post.posted_at)}
                >
                  {formatRelative(post.posted_at)}
                </td>
                {/* The card view has always had a bookmark; the table view hadn't, so
                    the same paper was saveable in one view and not the other. */}
                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <BookmarkButton
                    paperId={p.id}
                    teamId={teamId}
                    userId={userId}
                    bookmarked={bookmarked.has(p.id)}
                    className="text-muted hover:text-accent"
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CardSkeletons() {
  return (
    <div className={CARD_GRID}>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="h-1.5 w-full animate-pulse bg-surface-2" />
          <div className="flex flex-col gap-3 p-4">
            <div className="h-2.5 w-20 animate-pulse rounded bg-surface-2" />
            <div className="h-4 w-4/5 animate-pulse rounded bg-surface-2" />
            <div className="h-3 w-1/2 animate-pulse rounded bg-surface-2" />
            <div className="h-3 w-2/3 animate-pulse rounded bg-surface-2" />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState({
  mode,
  narrowed,
  onClear,
  onAdd,
}: {
  mode: SearchMode;
  narrowed: boolean;
  onClear: () => void;
  onAdd: () => void;
}) {
  const title =
    mode === "semantic"
      ? "No papers match that description"
      : narrowed
        ? "No papers match"
        : "No papers yet";
  const body =
    mode === "semantic"
      ? "Try describing the topic differently, or go back to keyword search."
      : narrowed
        ? "Try a different search term, or clear the filters."
        : "Add the first one — every paper your lab shares teaches Atlas its taste.";

  return (
    <div className="flex flex-col items-center gap-3 rounded-card border border-dashed border-border-strong px-6 py-16 text-center">
      <div className="font-semibold text-fg">{title}</div>
      <p className="max-w-sm text-sm text-muted">{body}</p>
      {narrowed ? (
        <Button variant="secondary" size="sm" onClick={onClear}>
          Reset
        </Button>
      ) : (
        <Button size="sm" onClick={onAdd}>
          <Plus size={14} /> Add a paper
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
