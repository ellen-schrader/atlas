import { type ReactNode, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import {
  AlertTriangle,
  ChevronDown,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
  Radar,
  Trash2,
  X,
} from "lucide-react";

import { SelectCheckbox } from "@/components/ExportBar";
import { SearchDialog } from "@/components/suggestions/SearchDialog";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import {
  decideSuggestions,
  deleteSearch,
  listSearches,
  listSuggestions,
  updateSearch,
} from "@/lib/api";
import {
  PAPER_SOURCE_LABEL,
  SAVED_SEARCHES_FEATURE,
  type SavedSearch,
  type Suggestion,
  sourcesLabel,
} from "@/lib/savedSearches";
import { cn, formatAuthors, formatDate, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/** After a search is saved it runs in the background; poll for its first
 *  suggestions this long. */
const FIRST_RUN_MS = 90_000;

function RequireSavedSearches({ children }: { children: ReactNode }) {
  const { features, featuresLoaded, featuresFailed } = useAppContext();
  if (featuresFailed)
    return (
      <p role="alert" className="p-8 text-sm text-danger">
        Couldn’t load this page. Check your connection and reload.
      </p>
    );
  if (!featuresLoaded) return null;
  if (!features.includes(SAVED_SEARCHES_FEATURE))
    return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function Suggestions() {
  return (
    <RequireSavedSearches>
      <SuggestionsPage />
    </RequireSavedSearches>
  );
}

function SuggestionsPage() {
  const { team } = useAppContext();
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, confirmDialog] = useConfirm();
  const [editing, setEditing] = useState<SavedSearch | "new" | null>(null);
  const [runningUntil, setRunningUntil] = useState(0);
  const [filter, setFilter] = useState<string>("all");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());

  const running = runningUntil > Date.now();
  const searches = useQuery({
    queryKey: ["saved-searches", team.id],
    queryFn: () => listSearches(team.id),
    refetchInterval: running ? 5000 : false,
  });
  const suggestions = useQuery({
    queryKey: ["suggestions", team.id],
    queryFn: () => listSuggestions(team.id),
    refetchInterval: running ? 5000 : false,
  });

  const byId = useMemo(
    () => new Map((searches.data ?? []).map((s) => [s.id, s])),
    [searches.data],
  );
  const all = suggestions.data ?? [];
  const shown =
    filter === "all" ? all : all.filter((s) => s.saved_search_id === filter);
  const shownPicked = shown.filter((s) => picked.has(s.id)).map((s) => s.id);

  const decide = useMutation({
    mutationFn: ({
      ids,
      decision,
    }: {
      ids: string[];
      decision: "import" | "dismiss";
    }) => decideSuggestions(team.id, ids, decision),
    onMutate: ({ ids }) => {
      // Off the list at once; the answer is on its way.
      const gone = new Set(ids);
      qc.setQueryData<Suggestion[]>(["suggestions", team.id], (cur) =>
        (cur ?? []).filter((s) => !gone.has(s.id)),
      );
      setPicked((cur) => new Set([...cur].filter((id) => !gone.has(id))));
    },
    onSuccess: (count, { decision }) => {
      if (decision === "import" && count > 0) {
        toast({
          message: `Adding ${count} ${count === 1 ? "paper" : "papers"} to ${team.name}’s library. They appear within a minute.`,
        });
        // Imports run in the background (a full lookup each, as posting a link
        // does): refresh the library once they have had time to land.
        for (const delay of [15_000, 60_000]) {
          setTimeout(() => {
            for (const key of ["paper-search", "paper-count"]) {
              void qc.invalidateQueries({ queryKey: [key] });
            }
          }, delay);
        }
      }
    },
    onError: () => toast({ message: "Couldn’t save that. Try again." }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["suggestions", team.id] });
      void qc.invalidateQueries({ queryKey: ["saved-searches", team.id] });
    },
  });

  const setActive = useMutation({
    mutationFn: (s: SavedSearch) =>
      updateSearch(team.id, s.id, { active: !s.active }),
    onSettled: () =>
      void qc.invalidateQueries({ queryKey: ["saved-searches", team.id] }),
    onError: () =>
      toast({ message: "Couldn’t change that search. Try again." }),
  });
  const remove = useMutation({
    mutationFn: (s: SavedSearch) => deleteSearch(team.id, s.id),
    onSuccess: (_v, s) => {
      if (filter === s.id) setFilter("all");
    },
    onSettled: () =>
      void qc.invalidateQueries({ queryKey: ["saved-searches", team.id] }),
    onError: () =>
      toast({ message: "Couldn’t delete that search. Try again." }),
  });

  async function askDelete(s: SavedSearch) {
    const ok = await confirm({
      title: `Delete “${s.name}”?`,
      body: "It stops running. Suggestions it already found stay in your list.",
      confirmLabel: "Delete search",
      danger: true,
    });
    if (ok) remove.mutate(s);
  }

  const togglePick = (id: string) =>
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleOpen = (id: string) =>
    setOpen((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allPicked = shown.length > 0 && shownPicked.length === shown.length;

  const list = searches.data ?? [];
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
            New papers from your saved searches on PubMed, bioRxiv/medRxiv and
            arXiv, every week. Only you see this list; what you import goes to{" "}
            {team.name}’s library.
          </p>
        </div>
        <Button onClick={() => setEditing("new")} disabled={list.length >= 10}>
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
        <EmptySearches onNew={() => setEditing("new")} />
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
            {list.map((s) => (
              <SearchRow
                key={s.id}
                search={s}
                onEdit={() => setEditing(s)}
                onToggle={() => setActive.mutate(s)}
                onDelete={() => void askDelete(s)}
              />
            ))}
          </ul>
        </section>
      )}

      {running && (
        <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <Loader2 size={14} className="animate-spin" aria-hidden />
          Running your search — its first suggestions appear here within a
          minute or so.
        </p>
      )}

      {list.length > 0 && !loading && (
        <section aria-labelledby="suggested" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="suggested" className="text-sm font-semibold text-fg">
              {all.length === 0
                ? "Nothing waiting"
                : `${all.length} waiting for you`}
            </h2>
            {list.length > 1 && all.length > 0 && (
              <div
                role="radiogroup"
                aria-label="Show suggestions from"
                className="flex flex-wrap gap-1.5"
              >
                <FilterChip
                  on={filter === "all"}
                  onClick={() => setFilter("all")}
                >
                  All · {all.length}
                </FilterChip>
                {list
                  .filter((s) => s.pending > 0)
                  .map((s) => (
                    <FilterChip
                      key={s.id}
                      on={filter === s.id}
                      onClick={() => setFilter(s.id)}
                    >
                      {s.name} ·{" "}
                      {all.filter((x) => x.saved_search_id === s.id).length}
                    </FilterChip>
                  ))}
              </div>
            )}
          </div>

          {all.length === 0 ? (
            <p className="rounded-card border border-dashed border-border p-6 text-sm text-muted">
              You’re up to date. Your searches run once a week, and anything new
              the lab doesn’t have yet will appear here.
            </p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <SelectCheckbox
                  checked={allPicked}
                  onChange={() =>
                    setPicked(
                      allPicked ? new Set() : new Set(shown.map((s) => s.id)),
                    )
                  }
                  label={allPicked ? "Select none" : "Select all shown"}
                />
                <span className="text-muted">
                  {shownPicked.length > 0
                    ? `${shownPicked.length} selected`
                    : "Select all"}
                </span>
                {shownPicked.length > 0 && (
                  <div className="ml-auto flex gap-2">
                    <Button
                      size="sm"
                      onClick={() =>
                        decide.mutate({ ids: shownPicked, decision: "import" })
                      }
                    >
                      <Plus size={13} aria-hidden />
                      Import {shownPicked.length}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() =>
                        decide.mutate({ ids: shownPicked, decision: "dismiss" })
                      }
                    >
                      Dismiss {shownPicked.length}
                    </Button>
                  </div>
                )}
              </div>
              <ul className="divide-y divide-border overflow-hidden rounded-card border border-border shadow-sm">
                {shown.map((s) => (
                  <SuggestionRow
                    key={s.id}
                    suggestion={s}
                    searchName={
                      list.length > 1 && s.saved_search_id
                        ? byId.get(s.saved_search_id)?.name
                        : undefined
                    }
                    picked={picked.has(s.id)}
                    abstractOpen={open.has(s.id)}
                    onPick={() => togglePick(s.id)}
                    onToggleAbstract={() => toggleOpen(s.id)}
                    onImport={() =>
                      decide.mutate({ ids: [s.id], decision: "import" })
                    }
                    onDismiss={() =>
                      decide.mutate({ ids: [s.id], decision: "dismiss" })
                    }
                  />
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      <SearchDialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        teamId={team.id}
        search={editing === "new" ? null : editing}
        onSaved={(_s, rerun) => {
          if (rerun) setRunningUntil(Date.now() + FIRST_RUN_MS);
        }}
      />
      {confirmDialog}
    </div>
  );
}

function EmptySearches({ onNew }: { onNew: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-card border border-dashed border-border p-6">
      <Radar size={22} className="text-accent" aria-hidden />
      <div>
        <p className="font-medium text-fg">
          Follow a topic, get the new papers every week
        </p>
        <p className="mt-1 max-w-[60ch] text-sm text-muted">
          Save a search — your PubMed alert string works as it is — and Atlas
          runs it on PubMed, bioRxiv/medRxiv and arXiv once a week. You pick
          which papers go into the library.
        </p>
      </div>
      <Button onClick={onNew}>
        <Plus size={15} aria-hidden />
        New search
      </Button>
    </div>
  );
}

function searchStatus(s: SavedSearch): { text: string; warn: boolean } {
  if (!s.active) return { text: "Paused", warn: false };
  if (s.last_error)
    return { text: `Last run had a problem: ${s.last_error}`, warn: true };
  if (!s.last_run_at) return { text: "Runs within a day", warn: false };
  return { text: `Ran ${formatRelative(s.last_run_at)}`, warn: false };
}

function SearchRow({
  search,
  onEdit,
  onToggle,
  onDelete,
}: {
  search: SavedSearch;
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
            {sourcesLabel(search.sources)} · {status.text}
          </span>
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
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
  searchName,
  picked,
  abstractOpen,
  onPick,
  onToggleAbstract,
  onImport,
  onDismiss,
}: {
  suggestion: Suggestion;
  searchName?: string;
  picked: boolean;
  abstractOpen: boolean;
  onPick: () => void;
  onToggleAbstract: () => void;
  onImport: () => void;
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
          {searchName && (
            <span className="text-faint"> · from “{searchName}”</span>
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
          onClick={onImport}
          aria-label={`Import “${p.title}”`}
        >
          <Plus size={13} aria-hidden />
          Import
        </Button>
        <IconButton label={`Dismiss “${p.title}”`} onClick={onDismiss}>
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
  children,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={cn(
        "grid h-8 w-8 place-items-center rounded-md text-faint transition hover:bg-surface-3",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        danger ? "hover:text-danger" : "hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

function FilterChip({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        on
          ? "border-accent/50 bg-accent-weak text-fg"
          : "border-border text-muted hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}
