import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
  ScanSearch,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import { SelectCheckbox } from "@/components/ExportBar";
import { RequireFeature } from "@/components/RequireFeature";
import { SearchDialog } from "@/components/suggestions/SearchDialog";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import {
  decideSuggestions,
  deleteSearch,
  listSearchIdeas,
  listSearches,
  listSuggestions,
  reorderSearches,
  updateSearch,
} from "@/lib/api";
import { invalidateAfterPost } from "@/lib/paperLookup";
import {
  ARXIV_BIOLOGY,
  PAPER_SOURCE_LABEL,
  SAVED_SEARCHES_FEATURE,
  type SavedSearch,
  type SearchFields,
  type SearchIdea,
  type Suggestion,
  sourcesLabel,
} from "@/lib/savedSearches";
import { cn, formatAuthors, formatDate, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/** After a search is saved it runs in the background; poll for its first
 *  suggestions until it has run, or this long at most. */
const FIRST_RUN_MS = 90_000;
/** Imports run in the background (a full lookup each, as posting a link
 *  does): refresh the library after these delays. */
const LIBRARY_REFRESH_MS = [15_000, 60_000];
/** Suggestions from searches since deleted (their search id is gone). */
const EARLIER = "earlier";
/** A person's saved searches per lab (the API's MAX_SEARCHES). */
const MAX_SEARCHES = 10;

export default function Suggestions() {
  return (
    <RequireFeature feature={SAVED_SEARCHES_FEATURE}>
      <SuggestionsPage />
    </RequireFeature>
  );
}

function SuggestionsPage() {
  const { team } = useAppContext();
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, confirmDialog] = useConfirm();
  const [editing, setEditing] = useState<SavedSearch | "new" | null>(null);
  // What a new search starts from (a suggested search), if anything.
  const [initial, setInitial] = useState<Partial<SearchFields>>();
  // The search running in the background since it was saved, if any.
  const [watching, setWatching] = useState<{
    id: string;
    until: number;
  } | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  // Search groups folded away.
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const timers = useRef<number[]>([]);

  const searches = useQuery({
    queryKey: ["saved-searches", team.id],
    queryFn: () => listSearches(team.id),
    refetchInterval: watching ? 5000 : false,
  });
  const suggestions = useQuery({
    queryKey: ["suggestions", team.id],
    queryFn: () => listSuggestions(team.id),
    refetchInterval: watching ? 5000 : false,
  });
  // Recomputed when the queries change: a search that covers an idea retires it.
  const ideas = useQuery({
    queryKey: [
      "search-ideas",
      team.id,
      (searches.data ?? []).map((x) => x.query).join("\n"),
    ],
    queryFn: () => listSearchIdeas(team.id),
    enabled: searches.isSuccess,
    staleTime: 5 * 60_000,
  });

  // Stop polling when the search has run (or failed), or when time is up --
  // a timer, since nothing else re-renders the page when the clock passes it.
  const watched = watching && searches.data?.find((x) => x.id === watching.id);
  const finished = !!watched && !!(watched.last_run_at || watched.last_error);
  useEffect(() => {
    if (!watching) return;
    if (finished) {
      setWatching(null);
      void qc.invalidateQueries({ queryKey: ["suggestions", team.id] });
      return;
    }
    const t = setTimeout(
      () => setWatching(null),
      Math.max(0, watching.until - Date.now()),
    );
    return () => clearTimeout(t);
  }, [watching, finished, qc, team.id]);
  useEffect(() => () => timers.current.forEach((t) => clearTimeout(t)), []);

  const list = searches.data ?? [];
  const byId = useMemo(() => new Map(list.map((x) => [x.id, x])), [list]);
  const all = suggestions.data ?? [];
  // One group per search that has something waiting, in the order of "Your
  // searches", then deleted searches'. A paper two searches found is in both.
  const groups = useMemo(() => {
    const items = new Map<string, Suggestion[]>();
    for (const x of all) {
      const live = x.search_ids.filter((id) => byId.has(id));
      for (const g of live.length ? live : [EARLIER]) {
        const group = items.get(g);
        if (group) group.push(x);
        else items.set(g, [x]);
      }
    }
    const named = list
      .filter((x) => items.has(x.id))
      .map((x) => ({
        id: x.id,
        name: x.name,
        items: items.get(x.id)!,
        // All it has waiting; the list holds its newest hundred (the API's PER_SEARCH).
        count: Math.max(x.pending, items.get(x.id)!.length),
      }));
    const earlier = items.get(EARLIER);
    return earlier
      ? [
          ...named,
          {
            id: EARLIER,
            name: "Deleted searches",
            items: earlier,
            count: earlier.length,
          },
        ]
      : named;
  }, [all, list, byId]);
  const pickedIds = all.filter((x) => picked.has(x.id)).map((x) => x.id);
  // Some search has more waiting than the page lists.
  const cut = groups.some((g) => g.count > g.items.length);

  const decide = useMutation({
    mutationFn: ({
      ids,
      decision,
    }: {
      ids: string[];
      decision: "import" | "dismiss";
    }) => decideSuggestions(team.id, ids, decision),
    onMutate: async ({ ids }) => {
      // Off the list at once; the answer is on its way. A poll already in
      // flight would put them back, so it is cancelled first.
      await qc.cancelQueries({ queryKey: ["suggestions", team.id] });
      const gone = new Set(ids);
      qc.setQueryData<Suggestion[]>(["suggestions", team.id], (cur) =>
        (cur ?? []).filter((x) => !gone.has(x.id)),
      );
      setPicked((cur) => new Set([...cur].filter((id) => !gone.has(id))));
    },
    onSuccess: ({ count, failed }, { ids, decision }) => {
      const papers = (n: number) => `${n} ${n === 1 ? "paper" : "papers"}`;
      if (decision === "import" && count > 0) {
        toast({
          message: failed
            ? `Adding ${papers(count)} to ${team.name}’s library; the other ${ids.length - count} couldn’t be added. Try those again.`
            : `Adding ${papers(count)} to ${team.name}’s library. They appear within a minute.`,
        });
        for (const delay of LIBRARY_REFRESH_MS) {
          timers.current.push(
            window.setTimeout(
              () => void invalidateAfterPost(qc, team.id),
              delay,
            ),
          );
        }
      } else if (failed) {
        toast({
          message: `Dismissed ${papers(count)}; the rest couldn’t be saved. Try again.`,
        });
      }
    },
    onError: () => toast({ message: "Couldn’t save that. Try again." }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["suggestions", team.id] });
      void qc.invalidateQueries({ queryKey: ["saved-searches", team.id] });
    },
  });

  const setActive = useMutation({
    mutationFn: (x: SavedSearch) =>
      updateSearch(team.id, x.id, { active: !x.active }),
    onSettled: () =>
      void qc.invalidateQueries({ queryKey: ["saved-searches", team.id] }),
    onError: () =>
      toast({ message: "Couldn’t change that search. Try again." }),
  });
  const reorder = useMutation({
    mutationFn: (ids: string[]) => reorderSearches(team.id, ids),
    onMutate: async (ids) => {
      // Moved at once; the groups below follow.
      await qc.cancelQueries({ queryKey: ["saved-searches", team.id] });
      qc.setQueryData<SavedSearch[]>(["saved-searches", team.id], (cur) =>
        cur ? ids.flatMap((id) => cur.find((x) => x.id === id) ?? []) : cur,
      );
    },
    onError: () => toast({ message: "Couldn’t move that search. Try again." }),
    onSettled: () =>
      void qc.invalidateQueries({ queryKey: ["saved-searches", team.id] }),
  });
  const move = (i: number, by: -1 | 1) => {
    const ids = list.map((x) => x.id);
    [ids[i], ids[i + by]] = [ids[i + by], ids[i]];
    reorder.mutate(ids);
  };
  const startFrom = (idea?: SearchIdea) => {
    setInitial(idea ? { name: idea.name, query: idea.query } : undefined);
    setEditing("new");
  };

  const remove = useMutation({
    mutationFn: (x: SavedSearch) => deleteSearch(team.id, x.id),
    // Its waiting papers went with it.
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["saved-searches", team.id] });
      void qc.invalidateQueries({ queryKey: ["suggestions", team.id] });
    },
    onError: () =>
      toast({ message: "Couldn’t delete that search. Try again." }),
  });

  async function askDelete(x: SavedSearch) {
    const ok = await confirm({
      title: `Delete “${x.name}”?`,
      body: "It stops running, and the papers it found that you haven’t added or dismissed go too.",
      confirmLabel: "Delete search",
      danger: true,
    });
    if (ok) remove.mutate(x);
  }

  const togglePick = (id: string) => setPicked((cur) => toggled(cur, id));
  const toggleOpen = (id: string) => setOpen((cur) => toggled(cur, id));
  // Folding a group unpicks it, so Add / Dismiss never act on hidden rows.
  const toggleFolded = (g: { id: string; items: Suggestion[] }) => {
    if (!folded.has(g.id)) {
      const hidden = new Set(g.items.map((x) => x.id));
      setPicked((cur) => new Set([...cur].filter((id) => !hidden.has(id))));
    }
    setFolded((cur) => toggled(cur, g.id));
  };
  // Pick a whole group, or unpick it when it is all picked already. A folded
  // group opens, so what is picked is in view.
  const pickGroup = (g: { id: string; items: Suggestion[] }) => {
    const items = g.items;
    setFolded((cur) => {
      const next = new Set(cur);
      next.delete(g.id);
      return next;
    });
    setPicked((cur) => {
      const next = new Set(cur);
      const every = items.every((x) => cur.has(x.id));
      for (const x of items) {
        if (every) next.delete(x.id);
        else next.add(x.id);
      }
      return next;
    });
  };

  const loading = searches.isPending || suggestions.isPending;
  const failed = searches.isError || suggestions.isError;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6 sm:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-display font-bold tracking-tight text-fg">
            Suggested papers
          </h1>
          <p className="mt-1.5 max-w-[62ch] text-sm text-muted">
            New papers that match your searches, every week. Add the good ones
            to {team.name}’s library and dismiss the rest. Only you see this
            list.
          </p>
        </div>
        <Button
          onClick={() => startFrom()}
          disabled={list.length >= MAX_SEARCHES}
        >
          <Plus size={15} aria-hidden />
          New search
        </Button>
      </div>

      {failed && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load your suggestions. Check your connection and reload.
        </p>
      )}
      {loading && !failed && (
        <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <Loader2 size={14} className="animate-spin" aria-hidden /> Loading…
        </p>
      )}

      {!loading && !failed && list.length === 0 && (
        <EmptySearches
          onNew={() => startFrom()}
          ideas={
            <SearchIdeas ideas={ideas.data ?? []} onUse={(i) => startFrom(i)} />
          }
        />
      )}

      {list.length > 0 && (
        <section
          aria-labelledby="your-searches"
          className="flex flex-col gap-2"
        >
          <h2 id="your-searches" className="text-sm font-semibold text-fg">
            Your searches
          </h2>
          <ul className="divide-y divide-border overflow-hidden rounded-card border border-border">
            {list.map((s, i) => (
              <SearchRow
                key={s.id}
                search={s}
                onUp={i > 0 ? () => move(i, -1) : undefined}
                onDown={i < list.length - 1 ? () => move(i, 1) : undefined}
                onEdit={() => setEditing(s)}
                onToggle={() => setActive.mutate(s)}
                onDelete={() => void askDelete(s)}
              />
            ))}
          </ul>
          {list.length > 1 && (
            <p className="text-xs text-faint">
              Papers are grouped by search in this order. Use the arrows to put
              the searches that matter most first.
            </p>
          )}
          {(ideas.data?.length ?? 0) > 0 && list.length < MAX_SEARCHES && (
            <details className="group mt-1">
              <summary className="inline-flex cursor-pointer select-none items-center gap-1.5 text-xs font-medium text-muted hover:text-fg">
                <Sparkles size={13} aria-hidden />
                Ideas for more searches
              </summary>
              <div className="mt-2">
                <SearchIdeas
                  ideas={ideas.data ?? []}
                  onUse={(i) => startFrom(i)}
                />
              </div>
            </details>
          )}
        </section>
      )}

      {watching && (
        <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <Loader2 size={14} className="animate-spin" aria-hidden />
          Running your search — its first suggestions appear here within a
          minute or so.
        </p>
      )}

      {(list.length > 0 || all.length > 0) && !loading && (
        <section aria-labelledby="suggested" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="suggested" className="text-sm font-semibold text-fg">
              {all.length === 0
                ? "No new papers"
                : `${all.length}${cut ? "+" : ""} new ${all.length === 1 ? "paper" : "papers"}`}
            </h2>
          </div>

          {all.length === 0 ? (
            <p className="rounded-card border border-dashed border-border p-6 text-sm text-muted">
              You’re all caught up. New papers the lab doesn’t have yet show up
              here after your searches’ next weekly run.
            </p>
          ) : (
            <>
              {groups.map((g) => {
                const isFolded = folded.has(g.id);
                const every = g.items.every((x) => picked.has(x.id));
                const listId = `group-${g.id}`;
                return (
                  <section
                    key={g.id}
                    aria-label={`From “${g.name}”`}
                    className="flex flex-col gap-2"
                  >
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => toggleFolded(g)}
                        aria-expanded={!isFolded}
                        aria-controls={listId}
                        className="inline-flex min-w-0 items-center gap-1 text-sm font-semibold text-fg hover:text-accent"
                      >
                        <ChevronDown
                          size={14}
                          className={cn(
                            "shrink-0 transition-transform",
                            isFolded && "-rotate-90",
                          )}
                          aria-hidden
                        />
                        <span className="truncate">{g.name}</span>
                        <span className="font-normal text-muted">
                          · {g.count}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => pickGroup(g)}
                        aria-pressed={every}
                        aria-label={`Select all ${g.items.length} from “${g.name}”`}
                        className="ml-auto shrink-0 text-xs font-medium text-muted hover:text-fg"
                      >
                        {every ? "Deselect all" : "Select all"}
                      </button>
                    </div>
                    {!isFolded && (
                      <ul
                        id={listId}
                        className="divide-y divide-border overflow-hidden rounded-card border border-border shadow-sm"
                      >
                        {g.items.map((s) => (
                          <SuggestionRow
                            key={s.id}
                            suggestion={s}
                            picked={picked.has(s.id)}
                            abstractOpen={open.has(s.id)}
                            busy={decide.isPending}
                            onPick={() => togglePick(s.id)}
                            onToggleAbstract={() => toggleOpen(s.id)}
                            onAdd={() =>
                              decide.mutate({ ids: [s.id], decision: "import" })
                            }
                            onDismiss={() =>
                              decide.mutate({
                                ids: [s.id],
                                decision: "dismiss",
                              })
                            }
                          />
                        ))}
                      </ul>
                    )}
                    {!isFolded && g.count > g.items.length && (
                      <p className="text-xs text-faint">
                        Showing the newest {g.items.length} of {g.count}. Add or
                        dismiss these to see the rest.
                      </p>
                    )}
                  </section>
                );
              })}
              {pickedIds.length > 0 && (
                <div
                  role="region"
                  aria-label="Selected papers"
                  className="sticky bottom-4 z-10 mx-auto flex flex-wrap items-center gap-2 rounded-card border border-border bg-surface px-4 py-2.5 text-sm shadow-lg"
                >
                  <span className="mr-2 font-medium text-fg">
                    {pickedIds.length} selected
                  </span>
                  <Button
                    size="sm"
                    disabled={decide.isPending}
                    onClick={() =>
                      decide.mutate({ ids: pickedIds, decision: "import" })
                    }
                  >
                    <Plus size={13} aria-hidden />
                    Add {pickedIds.length}
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={decide.isPending}
                    onClick={() =>
                      decide.mutate({ ids: pickedIds, decision: "dismiss" })
                    }
                  >
                    Dismiss {pickedIds.length}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setPicked(new Set())}
                  >
                    Clear
                  </Button>
                </div>
              )}
            </>
          )}
        </section>
      )}

      <SearchDialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        teamId={team.id}
        search={editing === "new" ? null : editing}
        initial={editing === "new" ? initial : undefined}
        onSaved={(s, rerun) => {
          // A paused search isn't run when its query changes.
          if (rerun && s.active)
            setWatching({ id: s.id, until: Date.now() + FIRST_RUN_MS });
        }}
      />
      {confirmDialog}
    </div>
  );
}

function EmptySearches({
  onNew,
  ideas,
}: {
  onNew: () => void;
  ideas: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-4 rounded-card border border-dashed border-border p-6">
      <ScanSearch size={22} className="text-accent" aria-hidden />
      <div>
        <p className="font-medium text-fg">Never miss a paper on your topic</p>
        <p className="mt-1 max-w-[60ch] text-sm text-muted">
          Type a few keywords, or paste a PubMed search. Every week Atlas checks
          PubMed, bioRxiv, medRxiv and arXiv and lists the new papers here.
        </p>
      </div>
      {ideas}
      <Button onClick={onNew} variant="secondary">
        <Plus size={15} aria-hidden />
        Write your own
      </Button>
    </div>
  );
}

/** Ready-made searches from the person's tags; "Use this" opens the form
 *  filled in, to preview and adjust before saving. */
function SearchIdeas({
  ideas,
  onUse,
}: {
  ideas: SearchIdea[];
  onUse: (idea: SearchIdea) => void;
}) {
  if (ideas.length === 0) return null;
  return (
    <section
      aria-label="Suggested searches"
      className="flex w-full flex-col gap-2"
    >
      <p className="text-xs font-medium text-muted">
        Start from one of these, based on your papers and tags:
      </p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {ideas.map((idea) => (
          <li
            key={idea.query}
            className="flex flex-col gap-1.5 rounded-card border border-border bg-surface p-3"
          >
            <p className="text-sm font-semibold text-fg">{idea.name}</p>
            <p className="break-words font-mono text-xs text-muted">
              {idea.query}
            </p>
            <div className="mt-auto flex items-center justify-between gap-2 pt-1">
              <span className="text-xs text-faint">{idea.reason}</span>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => onUse(idea)}
                aria-label={`Use the search “${idea.name}”`}
              >
                Use this
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** "biology", "all subjects", or the codes. */
function arxivLabel(codes: string[]): string {
  if (codes.length === 0) return "all subjects";
  if (codes.join() === ARXIV_BIOLOGY.join()) return "biology";
  return codes.join(", ");
}

function searchStatus(s: SavedSearch): { text: string; warn: boolean } {
  if (!s.active) return { text: "Paused", warn: false };
  if (s.last_error)
    return { text: `Last run had a problem: ${s.last_error}`, warn: true };
  if (!s.last_run_at) return { text: "First run within a day", warn: false };
  return { text: `Last ran ${formatRelative(s.last_run_at)}`, warn: false };
}

function SearchRow({
  search,
  onUp,
  onDown,
  onEdit,
  onToggle,
  onDelete,
}: {
  search: SavedSearch;
  /** Move it up or down the order; absent at either end. */
  onUp?: () => void;
  onDown?: () => void;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const status = searchStatus(search);
  return (
    <li
      className={cn(
        "flex items-start gap-3 px-4 py-3",
        !search.active && "opacity-70",
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-fg">
          {search.name}
          {search.pending > 0 && (
            <span className="ml-2 rounded-chip bg-accent-weak px-1.5 py-0.5 text-xs font-medium text-accent">
              {search.pending} new
            </span>
          )}
        </p>
        <p
          className="mt-0.5 truncate font-mono text-xs text-muted"
          title={search.query}
        >
          {search.query}
        </p>
        <p
          className={cn(
            "mt-1 flex items-start gap-1 text-xs",
            status.warn ? "text-danger" : "text-faint",
          )}
        >
          {status.warn && (
            <AlertTriangle size={12} className="mt-px shrink-0" aria-hidden />
          )}
          <span>
            {sourcesLabel(search.sources)}
            {search.sources.includes("arxiv") &&
              ` (${arxivLabel(search.arxiv_categories)})`}{" "}
            · {status.text}
          </span>
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        <IconButton
          label={`Move “${search.name}” up`}
          onClick={() => onUp?.()}
          disabled={!onUp}
        >
          <ArrowUp size={14} />
        </IconButton>
        <IconButton
          label={`Move “${search.name}” down`}
          onClick={() => onDown?.()}
          disabled={!onDown}
        >
          <ArrowDown size={14} />
        </IconButton>
        <IconButton label={`Edit “${search.name}”`} onClick={onEdit}>
          <Pencil size={14} />
        </IconButton>
        <IconButton
          label={
            search.active ? `Pause “${search.name}”` : `Resume “${search.name}”`
          }
          onClick={onToggle}
        >
          {search.active ? <Pause size={14} /> : <Play size={14} />}
        </IconButton>
        <IconButton label={`Delete “${search.name}”`} onClick={onDelete} danger>
          <Trash2 size={14} />
        </IconButton>
      </div>
    </li>
  );
}

function SuggestionRow({
  suggestion,
  picked,
  abstractOpen,
  busy,
  onPick,
  onToggleAbstract,
  onAdd,
  onDismiss,
}: {
  suggestion: Suggestion;
  picked: boolean;
  abstractOpen: boolean;
  /** An add or dismiss is on its way: no second click. */
  busy: boolean;
  onPick: () => void;
  onToggleAbstract: () => void;
  onAdd: () => void;
  onDismiss: () => void;
}) {
  const p = suggestion.paper;
  const meta = [
    p.authors.length ? formatAuthors(p.authors, 2) : null,
    p.venue,
    p.published_on ? formatDate(p.published_on) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li
      className={cn(
        "flex items-start gap-3 px-4 py-3",
        picked && "bg-accent-weak",
      )}
    >
      <div className="pt-0.5">
        <SelectCheckbox
          checked={picked}
          onChange={onPick}
          label={`Select “${p.title}”`}
        />
      </div>
      <div className="min-w-0 flex-1">
        <a
          href={p.url}
          target="_blank"
          rel="noreferrer"
          className="block text-sm font-semibold leading-snug text-fg hover:text-accent hover:underline"
        >
          {p.title}
        </a>
        <p className="mt-1 text-xs text-muted">
          {meta || "—"}
          {/* The source, unless the venue already says it (arXiv, bioRxiv). */}
          {p.venue !== PAPER_SOURCE_LABEL[p.source] && (
            <span className="ml-1.5 rounded-chip border border-border px-1.5 py-px text-[11px] text-faint">
              {PAPER_SOURCE_LABEL[p.source] ?? p.source}
            </span>
          )}
        </p>
        {p.abstract && (
          <button
            type="button"
            onClick={onToggleAbstract}
            aria-expanded={abstractOpen}
            className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-muted hover:text-fg"
          >
            <ChevronDown
              size={13}
              className={cn(
                "transition-transform",
                abstractOpen && "rotate-180",
              )}
              aria-hidden
            />
            {abstractOpen ? "Hide abstract" : "Abstract"}
          </button>
        )}
        {abstractOpen && p.abstract && (
          <p className="mt-1.5 max-w-[75ch] text-sm leading-relaxed text-muted">
            {p.abstract}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1 pt-0.5">
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={onAdd}
          aria-label={`Add “${p.title}” to the library`}
          title="Add to the library"
        >
          <Plus size={13} aria-hidden />
          Add
        </Button>
        <IconButton
          label={`Dismiss “${p.title}”`}
          onClick={onDismiss}
          disabled={busy}
        >
          <X size={15} />
        </IconButton>
      </div>
    </li>
  );
}

function IconButton({
  label,
  onClick,
  danger,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={cn(
        "grid h-8 w-8 place-items-center rounded-md text-faint transition hover:bg-surface-3 disabled:opacity-50",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        danger ? "hover:text-danger" : "hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

/** `cur` with `id` added, or taken out if it was there. */
function toggled(cur: Set<string>, id: string): Set<string> {
  const next = new Set(cur);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
