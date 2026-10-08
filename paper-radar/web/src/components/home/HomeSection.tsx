import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A Home section heading: it sits OUTSIDE the card, in a fixed 28px row with
 *  14px below, so card tops line up across columns whatever the headings contain. */
export function SectionHeading({
  title,
  controls,
  right,
  className,
}: {
  title: ReactNode;
  className?: string;
  /** Sits right after the title (e.g. a filter), outside the <h2>. */
  controls?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className={cn("mb-3.5 flex h-7 min-w-0 items-center gap-3", className)}>
      <h2 className="shrink-0 text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
        {title}
      </h2>
      {controls}
      {right && <div className="ml-auto flex min-w-0 items-center gap-2">{right}</div>}
    </div>
  );
}

/** "Label →" text link used in section headings. */
export function HeadingLink({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="tap-target whitespace-nowrap rounded-control text-xs font-medium text-muted transition hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      {children} →
    </button>
  );
}

/** Small segmented control (Lab feed filters, Trending tabs). */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex items-center gap-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "tap-target h-7 whitespace-nowrap rounded-control border px-2.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
            o.value === value
              ? "border-border-strong bg-surface-2 text-fg"
              : "border-transparent text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** 6px topic dot. Topic colours are data only (docs/dashboard.md §4); papers have
 *  no stable topic id yet, so `topic` is null today and the dot is the neutral
 *  --ch-off. */
export function TopicDot({ topic, className }: { topic?: number | null; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", className)}
      style={{ background: topicColor(topic) }}
    />
  );
}

export function topicColor(topic?: number | null): string {
  return topic && topic >= 1 && topic <= 6 ? `var(--ch-${topic})` : "var(--ch-off)";
}
