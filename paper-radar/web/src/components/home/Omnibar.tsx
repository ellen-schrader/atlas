import { type ClipboardEvent, type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Plus, Search } from "lucide-react";

import { AddPaperDialog } from "@/components/AddPaperDialog";
import { usePaperModal } from "@/components/PaperModal";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useDismissable } from "@/hooks/useDismissable";
import { usePaperLookup } from "@/hooks/usePaperLookup";
import { NO_FILTERS, usePaperCount, usePaperSearch } from "@/hooks/usePaperSearch";
import { postPaper } from "@/lib/api";
import { bareDoi, invalidateAfterPost, looksAddable, SOURCE_LABEL } from "@/lib/paperLookup";
import { cn, formatAuthors, formatRelative } from "@/lib/utils";

const MAX_RESULTS = 5;

/** One input, two jobs (docs/dashboard.md §3.2): type to search the lab, or paste
 *  a DOI / link to add it. The mode follows what's in the box. */
export function Omnibar({
  teamId,
  teamName,
  mobile,
}: {
  teamId: string;
  teamName: string;
  mobile: boolean;
}) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { openPaper } = usePaperModal();
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  /** The paste we've asked the server to resolve; null until paste / ↵. */
  const [target, setTarget] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<string | null>(null); // paper id
  const [addError, setAddError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ initialUrl?: string } | null>(null);

  const trimmed = value.trim();
  const mode: "none" | "add" | "search" = !trimmed ? "none" : looksAddable(trimmed) ? "add" : "search";

  const q = useDebouncedValue(mode === "search" ? trimmed : "", 150);
  const search = usePaperSearch(teamId, q, NO_FILTERS, "shared", Boolean(q));
  const { data: total } = usePaperCount(teamId, q, NO_FILTERS, Boolean(q));
  const results = q ? (search.data?.pages[0] ?? []).slice(0, MAX_RESULTS) : [];

  const lookupInput = mode === "add" && target === trimmed ? trimmed : null;
  const lookup = usePaperLookup(teamId, lookupInput);

  // Esc never reaches the input's onKeyDown while the dropdown is open: the
  // dismiss hook takes it in the capture phase. So "Esc clears" lives here too.
  // Off while our own AddPaperDialog is up: its Escape and backdrop clicks are
  // the dialog's, and this capture-phase listener would otherwise swallow them.
  // Once a paper is added, the link has done its job: any way of leaving the
  // dropdown resets the bar rather than leaving the URL sitting in it.
  useDismissable(wrapRef, open && dialog === null, (reason) =>
    reason === "escape" || added ? clear() : setOpen(false),
  );

  // ⌘K / Ctrl+K focuses the bar from anywhere on Home.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function change(next: string) {
    setValue(next);
    setOpen(true);
    setActive(-1);
    setAdded(null);
    setAddError(null);
  }

  function clear() {
    change("");
    setTarget(null);
    setOpen(false);
  }

  function onPaste(e: ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData("text").trim();
    // Only when the paste becomes the whole value — pasting into the middle of a
    // search isn't a request to resolve anything.
    if (pasted && !trimmed && looksAddable(pasted)) setTarget(pasted);
  }

  async function add() {
    const data = lookup.data;
    if (!data || data.duplicate || !data.resolved.title || adding) return;
    const r = data.resolved;
    setAdding(true);
    setAddError(null);
    try {
      const res = await postPaper(data.url, teamId, {
        title: r.title,
        authors: r.authors ?? [],
        venue: r.venue,
        year: r.year,
        // The bare DOI, as AddPaperDialog sends it: papers.doi dedupes on it.
        doi: r.doi ? (bareDoi(r.doi) ?? r.doi.trim()) : null,
        abstract: r.abstract,
        keywords: r.keywords ?? [],
        source: r.source,
      });
      await invalidateAfterPost(qc, teamId);
      setAdded(res.paper_id);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : String(err));
    } finally {
      setAdding(false);
    }
  }

  function openResult(paperId: string) {
    if (added) clear();
    else setOpen(false);
    openPaper(paperId);
  }

  function seeAll() {
    navigate(`/papers?q=${encodeURIComponent(trimmed)}`);
  }

  // Keyboard-navigable options: the search results, then "See all in Papers".
  const optionCount = mode === "search" && q ? results.length + 1 : 0;

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      clear();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!optionCount) return;
      e.preventDefault();
      setOpen(true);
      setActive((i) =>
        e.key === "ArrowDown" ? (i + 1) % optionCount : (i - 1 + optionCount) % optionCount,
      );
      return;
    }
    if (e.key !== "Enter") return;
    e.preventDefault();
    setOpen(true);
    if (mode === "search") {
      if (active >= 0 && active < results.length) openResult(results[active].papers.id);
      else seeAll();
    } else if (mode === "add") {
      if (target !== trimmed) setTarget(trimmed);
      else if (added) openResult(added);
      else if (lookup.data?.duplicate) openResult(lookup.data.duplicate.paperId);
      else void add();
    }
  }

  function onAddButton() {
    if (mode === "add") {
      inputRef.current?.focus();
      setOpen(true);
      if (target !== trimmed) setTarget(trimmed);
      else void add();
    } else {
      setOpen(false);
      setDialog({});
    }
  }

  const addMode = mode === "add";
  const showDropdown = open && mode !== "none";
  const detected = bareDoi(trimmed) ? "DOI detected" : "Link detected";

  return (
    <div ref={wrapRef} className="relative min-w-0">
      <div
        className={cn(
          "flex items-center gap-2 rounded-card border bg-surface pl-3.5 pr-1.5 transition",
          mobile ? "h-[54px]" : "h-[52px]",
          addMode
            ? "border-accent shadow-[0_0_0_4px_var(--accent-weak)]"
            : "border-border focus-within:border-border-strong",
        )}
      >
        <Search size={17} className="shrink-0 text-muted" aria-hidden />
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => change(e.target.value)}
          onPaste={onPaste}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-expanded={showDropdown}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          aria-label="Search papers, or paste a DOI or link to add"
          placeholder={
            mobile
              ? "Search, or paste a DOI to add"
              : "Search by title, author or tag, or paste a DOI or link to add"
          }
          // 16px on phones: anything smaller makes iOS zoom in on focus.
          className={cn(
            "h-full min-w-0 flex-1 bg-transparent text-fg outline-none placeholder:text-faint",
            mobile ? "text-base" : "text-sm",
          )}
        />
        {addMode && !mobile && (
          <span className="shrink-0 rounded-chip bg-accent-weak px-2 py-0.5 text-[11px] font-semibold text-accent">
            {detected}
          </span>
        )}
        {!mobile && !addMode && (
          <kbd className="shrink-0 rounded-md border border-border px-1.5 py-0.5 font-mono text-[10.5px] text-faint">
            ⌘K
          </kbd>
        )}
        <button
          type="button"
          onClick={onAddButton}
          aria-label="Add paper"
          className={cn(
            "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-control bg-accent font-semibold text-accent-fg transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
            mobile ? "h-11 w-11" : "h-10 px-3.5 text-sm",
          )}
        >
          <Plus size={mobile ? 18 : 16} />
          {!mobile && "Add paper"}
        </button>
      </div>

      {showDropdown && (
        <div
          id={listId}
          role="listbox"
          aria-label={addMode ? "Paper to add" : "Search results"}
          className="absolute inset-x-0 top-full z-30 mt-2 overflow-hidden rounded-card border border-border bg-surface shadow-2xl"
        >
          {addMode ? (
            <AddPanel
              pending={target !== trimmed}
              lookup={lookup}
              adding={adding}
              added={added}
              addError={addError}
              teamName={teamName}
              onAdd={() => void add()}
              onOpen={openResult}
              onManual={() => {
                setOpen(false);
                setDialog({ initialUrl: trimmed });
              }}
              onLookUp={() => setTarget(trimmed)}
            />
          ) : (
            <>
              <div className="border-b border-border px-4 py-2 text-eyebrow font-bold uppercase tracking-eyebrow text-faint">
                {search.isLoading || !q ? "Searching…" : `${total ?? results.length} matches`}
              </div>
              {q && !search.isLoading && results.length === 0 && (
                <div className="px-4 py-4 text-sm text-muted">No papers in {teamName} match that.</div>
              )}
              {results.map((post, i) => (
                <div
                  key={post.id}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={active === i}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => openResult(post.papers.id)}
                  onMouseEnter={() => setActive(i)}
                  className={cn(
                    "cursor-pointer px-4 py-2.5",
                    active === i && "bg-surface-2",
                  )}
                >
                  <div className="truncate text-sm font-medium">{post.papers.title ?? post.papers.url}</div>
                  <div className="mt-0.5 truncate text-meta text-muted">
                    {[post.papers.venue, post.papers.year].filter(Boolean).join(" · ")}
                  </div>
                </div>
              ))}
              {q && (
                <div
                  id={`${listId}-${results.length}`}
                  role="option"
                  aria-selected={active === results.length}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={seeAll}
                  onMouseEnter={() => setActive(results.length)}
                  className={cn(
                    "cursor-pointer border-t border-border px-4 py-2.5 text-sm font-medium text-muted",
                    active === results.length && "bg-surface-2 text-fg",
                  )}
                >
                  See all in Papers →
                </div>
              )}
            </>
          )}
        </div>
      )}

      <AddPaperDialog
        open={dialog !== null}
        onClose={() => setDialog(null)}
        teamId={teamId}
        teamName={teamName}
        initialUrl={dialog?.initialUrl}
        onAdded={(paperId) => {
          setDialog(null);
          clear();
          openPaper(paperId);
        }}
      />
    </div>
  );
}

function AddPanel({
  pending,
  lookup,
  adding,
  added,
  addError,
  teamName,
  onAdd,
  onOpen,
  onManual,
  onLookUp,
}: {
  pending: boolean;
  lookup: ReturnType<typeof usePaperLookup>;
  adding: boolean;
  added: string | null;
  addError: string | null;
  teamName: string;
  onAdd: () => void;
  onOpen: (paperId: string) => void;
  onManual: () => void;
  onLookUp: () => void;
}) {
  if (pending) {
    return (
      <PanelRow>
        <span className="text-muted">Press ↵ to look this up.</span>
        <PanelButton onClick={onLookUp}>Look up</PanelButton>
      </PanelRow>
    );
  }
  if (lookup.isLoading) {
    return (
      <PanelRow>
        <span className="inline-flex items-center gap-2 text-muted">
          <Loader2 size={14} className="animate-spin" /> Looking it up…
        </span>
      </PanelRow>
    );
  }
  if (lookup.isError || !lookup.data) {
    return (
      <PanelRow>
        <span className="text-muted">
          {lookup.error instanceof Error ? lookup.error.message : "That didn’t resolve."}
        </span>
        <PanelButton onClick={onManual}>Add it another way →</PanelButton>
      </PanelRow>
    );
  }

  const { resolved: r, duplicate } = lookup.data;

  // Before the duplicate check: adding refreshes the lookup, which then finds
  // the paper we just added.
  if (added) {
    return (
      <div className="p-4">
        <div className="text-sm font-semibold">{r.title ?? duplicate?.title ?? "This paper"}</div>
        <div className="mt-1 flex items-center justify-between gap-3">
          <span className="inline-flex items-center gap-1.5 text-sm font-medium text-accent">
            <Check size={15} /> Added to {teamName}
          </span>
          <PanelButton onClick={() => onOpen(added)}>Open →</PanelButton>
        </div>
      </div>
    );
  }

  if (duplicate) {
    return (
      <div className="p-4">
        <div className="text-sm font-semibold">{duplicate.title ?? r.title ?? "This paper"}</div>
        <div className="mt-1 flex items-center justify-between gap-3">
          <span className="text-meta text-muted">
            Already shared{duplicate.sharedBy ? ` by ${duplicate.sharedBy}` : ""}
            {duplicate.sharedAt ? ` · ${formatRelative(duplicate.sharedAt)}` : ""}
          </span>
          <PanelButton onClick={() => onOpen(duplicate.paperId)}>Open →</PanelButton>
        </div>
      </div>
    );
  }

  // A bot-walled page resolves to a record with no title: the dialog's recovery
  // step (try the DOI / PubMed link) is the way on.
  if (!r.title) {
    return (
      <PanelRow>
        <span className="text-muted">Couldn’t read that page.</span>
        <PanelButton onClick={onManual}>Try its DOI or add by hand →</PanelButton>
      </PanelRow>
    );
  }

  const source = SOURCE_LABEL[r.source] ?? null;
  const eyebrow = [source && `Found via ${source}`, r.venue, r.year].filter(Boolean).join(" · ");
  const suggested = (r.keywords ?? []).slice(0, 3);

  return (
    <div className="p-4">
      {eyebrow && (
        <div className="text-eyebrow font-bold uppercase tracking-eyebrow text-faint">{eyebrow}</div>
      )}
      <div className="mt-1.5 text-card font-semibold tracking-snug">{r.title}</div>
      {r.authors?.length > 0 && (
        <div className="mt-1 truncate text-meta text-muted">{formatAuthors(r.authors, 3)}</div>
      )}
      {suggested.length > 0 && (
        <div className="mt-1.5 truncate text-meta text-faint">
          suggested tags <span className="font-mono">{suggested.join(", ")}</span>
        </div>
      )}
      {addError && <div className="mt-2 text-meta text-danger">{addError}</div>}
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={onAdd}
          disabled={adding}
          className="inline-flex h-9 items-center gap-1.5 rounded-control bg-accent px-3.5 text-sm font-semibold text-accent-fg transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
        >
          {adding ? <Loader2 size={14} className="animate-spin" /> : <Plus size={15} />}
          Add to {teamName}
        </button>
      </div>
    </div>
  );
}

function PanelRow({ children }: { children: ReactNode }) {
  return <div className="flex items-center justify-between gap-3 px-4 py-3.5 text-sm">{children}</div>;
}

function PanelButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="shrink-0 whitespace-nowrap rounded-control text-sm font-medium text-muted transition hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      {children}
    </button>
  );
}
