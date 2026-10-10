import { X } from "lucide-react";
import { type KeyboardEvent, useId, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export interface SearchableOption {
  value: string;
  /** Paper count, shown muted after the name. */
  n?: number;
}

/** Shown before anything is typed. Options arrive most-used first, so the head
 *  of the list is the useful part; the long tail is a search away. */
const TOP_N = 20;
/** Cap on matches rendered while typing, so a one-letter query over thousands
 *  of tags doesn't build thousands of rows. */
const MAX_MATCHES = 50;

/** A single-value picker for long lists (tags, authors, venues): a text box that
 *  filters the options as you type (case-insensitive, anywhere in the name), with
 *  arrow keys, Enter and Escape. The list renders in flow, below the box, so it
 *  works inside a popover that clips overflow.
 *
 *  `value` is kept selectable even when it isn't among `options` (e.g. a tag that
 *  arrived via ?tag= but isn't one of the lab's own), so the box never claims
 *  "Any" while a filter is still on. */
export function SearchableSelect({
  label,
  anyLabel,
  value,
  onChange,
  options,
}: {
  label: string;
  /** Placeholder for "no filter", e.g. "Any tag". */
  anyLabel: string;
  value: string | null;
  onChange: (v: string | null) => void;
  options: SearchableOption[];
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const id = useId();
  const listId = `${id}-list`;

  const { shown, more } = useMemo(() => {
    const all =
      value && !options.some((o) => o.value === value) ? [{ value }, ...options] : options;
    const q = query.trim().toLowerCase();
    if (!q) return { shown: all.slice(0, TOP_N), more: Math.max(all.length - TOP_N, 0) };
    const matches = all.filter((o) => o.value.toLowerCase().includes(q));
    return { shown: matches.slice(0, MAX_MATCHES), more: Math.max(matches.length - MAX_MATCHES, 0) };
  }, [options, value, query]);

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
          className="max-h-52 overflow-y-auto rounded-control border border-border"
        >
          {shown.length === 0 && (
            <div className="px-2.5 py-2 text-sm text-muted">
              {options.length === 0 ? "None yet" : "No matches"}
            </div>
          )}
          {shown.map((o, i) => (
            <div
              key={o.value}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={o.value === value}
              // Keep focus in the box, so blur doesn't close the list first.
              onMouseDown={(e) => e.preventDefault()}
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
          {more > 0 && (
            <div className="border-t border-border px-2.5 py-1.5 text-xs text-faint">
              {query.trim() ? `${more} more — keep typing to narrow` : `${more} more — type to search`}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
