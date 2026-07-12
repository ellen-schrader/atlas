import { type FormEvent, useRef, useState } from "react";
import { Check, Plus } from "lucide-react";

import { useFigureCategories } from "@/hooks/useFigures";
import { mergeCategories, normalizeCategory } from "@/lib/figures";
import { cn } from "@/lib/utils";

/** Lab-defined category chooser: pick from broad defaults + the categories this
 *  lab has already used, or add your own. Categories are free text, so a typed
 *  value that case-insensitively matches an existing one reuses that spelling. */
export function CategoryPicker({
  teamId,
  value,
  onChange,
}: {
  teamId: string;
  value: string;
  onChange: (category: string) => void;
}) {
  const { data: used } = useFigureCategories(teamId);
  const options = mergeCategories((used ?? []).map((u) => u.category));

  // Keep the current value visible even if it's a custom one not in the list yet.
  const shown =
    value.trim() && !options.some((o) => normalizeCategory(o) === normalizeCategory(value))
      ? [value.trim(), ...options]
      : options;

  const [adding, setAdding] = useState(false);
  const [custom, setCustom] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Commit runs on blur only, so there's exactly one code path: Enter submits the
  // form, which blurs the input, which commits. Selecting/keying elsewhere blurs
  // too. Avoids the earlier onSubmit+onBlur double-fire.
  function commit() {
    const t = custom.trim();
    setCustom("");
    setAdding(false);
    if (!t) return;
    const existing = options.find((o) => normalizeCategory(o) === normalizeCategory(t));
    onChange(existing ?? t);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    inputRef.current?.blur();
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {shown.map((c) => {
        const on = normalizeCategory(c) === normalizeCategory(value);
        return (
          <button
            key={c}
            type="button"
            onClick={() => onChange(on ? "" : c)}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition",
              on
                ? "border-accent bg-accent-weak text-accent"
                : "border-border text-muted hover:border-accent",
            )}
          >
            {on && <Check size={12} />}
            {c}
          </button>
        );
      })}

      {adding ? (
        <form onSubmit={onSubmit} className="inline-flex items-center gap-1">
          <input
            ref={inputRef}
            autoFocus
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            onBlur={commit}
            placeholder="New category"
            className="w-32 rounded-full border border-accent bg-surface px-2.5 py-1 text-xs text-fg placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-accent"
          />
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2.5 py-1 text-xs text-faint transition hover:border-accent hover:text-accent"
        >
          <Plus size={12} /> Add category
        </button>
      )}
    </div>
  );
}
