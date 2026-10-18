import { type ReactNode, useRef, useState } from "react";
import { Navigate } from "react-router-dom";
import { Check, ChevronDown } from "lucide-react";

import { useDismissable } from "@/hooks/useDismissable";
import { THERAPY_CLASSES, THERAPY_COLOR, TRIALS_FEATURE, type TherapyClass } from "@/lib/trials";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/** Renders its children only when clinical trials is on for the user in this
 *  lab; otherwise sends them home, as if the page didn't exist. */
export function RequireTrials({ children }: { children: ReactNode }) {
  const { features, featuresLoaded } = useAppContext();
  if (!featuresLoaded) return null;
  if (!features.includes(TRIALS_FEATURE)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

/** Every trials page ends with this. */
export function TrialsDisclaimer() {
  return (
    <p className="border-t border-border pt-4 text-meta text-faint">
      For research and evidence review. Registry data can lag protocols. Not a recommendation for
      individual patients.
    </p>
  );
}

export function TherapySwatch({ therapy, className }: { therapy: TherapyClass; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block h-2.5 w-2.5 shrink-0 rounded-[3px]", className)}
      style={{
        background: THERAPY_COLOR[therapy],
        // The neutral channel needs an edge to read on the surface.
        boxShadow: therapy === "chemotherapy" ? "inset 0 0 0 1px var(--border-strong)" : undefined,
      }}
    />
  );
}

/** Therapy classes as swatch + label: the label is always there, so colour is
 *  never the only carrier. */
export function TherapyList({ therapies }: { therapies: TherapyClass[] }) {
  if (therapies.length === 0) return <span className="text-faint">—</span>;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1">
      {therapies.map((t) => (
        <span key={t} className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <TherapySwatch therapy={t} />
          {THERAPY_CLASSES[t]}
        </span>
      ))}
    </span>
  );
}

export interface FilterOption {
  value: string;
  label: string;
  /** Trials this option would show, given the other filters. */
  count: number;
  swatch?: TherapyClass;
}

/** A multi-select filter: a button with a count badge, and a checklist with
 *  per-option counts. */
export function FilterMenu({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: FilterOption[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  useDismissable(ref, open, (reason) => {
    setOpen(false);
    if (reason === "escape") buttonRef.current?.focus();
  });
  const active = selected.length > 0;
  return (
    <div ref={ref} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex min-h-10 items-center gap-2 rounded-control border px-3 text-sm font-medium transition",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          active || open
            ? "border-accent/50 bg-accent-weak text-fg"
            : "border-border bg-surface text-fg hover:border-border-strong",
        )}
      >
        {label}
        {active && (
          <span className="grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1.5 text-[11px] font-semibold text-accent-fg">
            {selected.length}
          </span>
        )}
        <ChevronDown size={14} aria-hidden className="text-muted" />
      </button>
      {open && (
        <div
          role="group"
          aria-label={label}
          className="absolute left-0 top-full z-30 mt-1.5 min-w-60 rounded-card border border-border bg-surface p-1.5 shadow-lg"
        >
          {options.map((o) => {
            const on = selected.includes(o.value);
            return (
              <button
                key={o.value}
                type="button"
                role="checkbox"
                aria-checked={on}
                onClick={() => onToggle(o.value)}
                className={cn(
                  "flex min-h-9 w-full items-center gap-2.5 rounded-control px-2 text-left text-sm transition",
                  "hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  o.count === 0 && !on && "text-faint",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "grid h-4 w-4 shrink-0 place-items-center rounded-[4px]",
                    on ? "bg-accent text-accent-fg" : "border border-border-strong",
                  )}
                >
                  {on && <Check size={12} strokeWidth={3} />}
                </span>
                {o.swatch && <TherapySwatch therapy={o.swatch} />}
                <span className="flex-1">{o.label}</span>
                <span className="font-mono text-meta text-muted">{o.count}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
