import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { type KeyboardEvent, useId, useRef, useState } from "react";

import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { cn } from "@/lib/utils";

export interface SearchableOption {
  value: string;
  /** Paper count, shown muted after the name. */
  n?: number;
}

/** Fetch up to `limit` options whose name contains `q` (all when `q` is empty),
 *  most-used first. */
export type LoadOptions = (q: string, limit: number) => Promise<SearchableOption[]>;

/** Shown before anything is typed: the most-used options. The long tail is a
 *  search away. */
const TOP_N = 20;
/** Matches shown while typing. */
const MAX_MATCHES = 50;

/** A single-value picker for long lists (tags, authors, venues): a text box that
 *  searches as you type (case-insensitive, anywhere in the name), with arrow
 *  keys, Enter and Escape. The search runs on the server — a lab's authors alone
 *  outgrow the 1000 rows PostgREST will return — and only while the list is
 *  open, so a page that never opens the menu never fetches its options. The list
 *  renders in flow, below the box, so it works inside a popover that clips
 *  overflow.
 *
 *  `value` is kept selectable even when the server doesn't return it (e.g. a tag
 *  that arrived via ?tag= but isn't one of the lab's own), so the box never
 *  claims "Any" while a filter is still on. */
export function SearchableSelect({
  label,
  anyLabel,
  value,
  onChange,
  queryKey,
  load,
}: {
  label: string;
  /** Placeholder for "no filter", e.g. "Any tag". */
  anyLabel: string;
  value: string | null;
  onChange: (v: string | null) => void;
  /** Cache key prefix, e.g. ["team-authors", teamId]; the query is appended. */
  queryKey: readonly unknown[];
  load: LoadOptions;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const id = useId();
  const listId = `${id}-list`;

  const q = useDebouncedValue(query.trim(), 200);
  const limit = q ? MAX_MATCHES : TOP_N;
  const { data, isPending } = useQuery({
    queryKey: [...queryKey, "search", q, limit],
    // One extra row says whether there are more than we show.
    queryFn: () => load(q, limit + 1),
    enabled: open,
    staleTime: 60 * 1000,
    placeholderData: keepPreviousData,
  });

  const rows = data ?? [];
  const more = rows.length > limit;
  let shown = rows.slice(0, limit);
  if (value && !q && !shown.some((o) => o.value === value)) shown = [{ value }, ...shown];

  function close() {
    setOpen(false);
    setQuery("");
    setActive(0);
  }

  function choose(v: string | null) {
    onChange(v);
    close();
    inputRef.current?.blur();
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      if (!open) return;
      // Close just this list, not the popover around it.
      e.preventDefault();
      e.stopPropagation();
      close();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      if (!shown.length) return;
      setActive((i) =>
        e.key === "ArrowDown" ? (i + 1) % shown.length : (i - 1 + shown.length) % shown.length,
      );
      return;
    }
    if (e.key === "Enter" && open && shown[active]) {
      e.preventDefault();
      choose(shown[active].value);
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted">
        {label}
      </label>
      <div className="relative">
        <input
          ref={inputRef}
          id={id}
          // Closed, the box shows the current choice; open, it's the search.
          value={open ? query : (value ?? "")}
          placeholder={open && value ? value : anyLabel}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={close}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && shown[active] ? `${listId}-${active}` : undefined}
          autoComplete="off"
          className={cn(
            "w-full rounded-control border border-border bg-surface py-1.5 pl-2 text-sm text-fg transition placeholder:text-faint hover:border-border-strong focus:border-accent focus:outline-none",
            value ? "pr-7" : "pr-2",
          )}
        />
        {value && !open && (
          <button
            type="button"
            onClick={() => choose(null)}
            aria-label={`Clear ${label.toLowerCase()} filter`}
            className="absolute right-1.5 top-1/2 grid h-5 w-5 -translate-y-1/2 place-items-center rounded text-faint hover:bg-surface-2 hover:text-fg"
          >
            <X size={12} />
          </button>
        )}
      </div>

      {open && (
        <div
          id={listId}
          role="listbox"
          aria-label={label}
          // Anywhere in the list — a row, the footer, the scrollbar — keeps focus
          // in the box, so its blur doesn't close the list mid-click or mid-scroll.
          onMouseDown={(e) => e.preventDefault()}
          className="max-h-52 overflow-y-auto rounded-control border border-border"
        >
          {shown.length === 0 && (
            <div className="px-2.5 py-2 text-sm text-muted">
              {isPending ? "Loading…" : q ? "No matches" : "None yet"}
            </div>
          )}
          {shown.map((o, i) => (
            <div
              key={o.value}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={o.value === value}
              onClick={() => choose(o.value)}
              onMouseEnter={() => setActive(i)}
              className={cn(
                "flex cursor-pointer items-baseline justify-between gap-2 px-2.5 py-1.5 text-sm",
                i === active && "bg-surface-2",
                o.value === value ? "font-medium text-accent" : "text-fg",
              )}
            >
              <span className="min-w-0 truncate">{o.value}</span>
              {o.n != null && <span className="shrink-0 text-xs tabular-nums text-faint">{o.n}</span>}
            </div>
          ))}
          {more && (
            <div className="border-t border-border px-2.5 py-1.5 text-xs text-faint">
              {q ? "More match — keep typing to narrow" : "More — type to search"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
