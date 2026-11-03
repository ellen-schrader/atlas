import { ChevronRight, Star } from "lucide-react";

import { Segmented } from "@/components/home/HomeSection";
import {
  RANGE_SUB,
  RANGES,
  type FacetItem,
  type FacetKind,
  type Range,
  sparkPath,
} from "@/lib/projectFacets";
import { cn } from "@/lib/utils";

export interface Facet {
  kind: FacetKind;
  key: string;
}

export function facetName(f: Facet): string {
  return f.kind === "tag" ? f.key : `${f.key} lab`;
}

/** "Around this project": the tags and labs (last authors) among the papers
 *  closest to it, all time by default. Each row: follow, a sparkline over the
 *  range, how many of its related papers are in the project, and the ones that
 *  aren't, which opens them in Suggested. */
export function AroundProject({
  tags,
  labs,
  nRelated,
  range,
  onRange,
  picked,
  onPick,
  onHover,
  onFollow,
  onGap,
  loading,
}: {
  tags: FacetItem[];
  labs: FacetItem[];
  nRelated: number;
  range: Range;
  onRange: (r: Range) => void;
  picked: Facet | null;
  onPick: (f: Facet | null) => void;
  onHover: (f: Facet | null) => void;
  onFollow: (f: Facet, on: boolean) => void;
  onGap: (f: Facet) => void;
  loading: boolean;
}) {
  return (
    <section aria-labelledby="around-h" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 id="around-h" className="text-heading font-bold tracking-tight">
          Around this project
        </h2>
        <span className="text-meta text-muted">
          {nRelated} related library {nRelated === 1 ? "paper" : "papers"}, the closest to it
        </span>
        <div className="ml-auto">
          <Segmented value={range} onChange={onRange} label="Time range for tags and labs" options={RANGES} />
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <FacetCard
          title="Tags"
          items={tags}
          range={range}
          picked={picked}
          onPick={onPick}
          onHover={onHover}
          onFollow={onFollow}
          onGap={onGap}
          loading={loading}
          foot="Followed tags suggest their related papers even below the line."
        />
        <FacetCard
          title="Labs"
          items={labs}
          range={range}
          picked={picked}
          onPick={onPick}
          onHover={onHover}
          onFollow={onFollow}
          onGap={onGap}
          loading={loading}
          foot="A lab is a paper's last author."
        />
      </div>
    </section>
  );
}

function FacetCard({
  title,
  items,
  range,
  picked,
  onPick,
  onHover,
  onFollow,
  onGap,
  loading,
  foot,
}: {
  title: string;
  items: FacetItem[];
  range: Range;
  picked: Facet | null;
  onPick: (f: Facet | null) => void;
  onHover: (f: Facet | null) => void;
  onFollow: (f: Facet, on: boolean) => void;
  onGap: (f: Facet) => void;
  loading: boolean;
  foot: string;
}) {
  return (
    <div className="flex flex-col rounded-card border border-border bg-surface px-2 pb-2 pt-3">
      <div className="flex items-baseline gap-2 border-b border-border px-2 pb-2">
        <h3 className="text-eyebrow font-bold uppercase tracking-eyebrow text-muted">{title}</h3>
        <span className="text-[11px] text-faint">{RANGE_SUB[range]}</span>
      </div>
      <div
        aria-hidden
        className="flex items-center gap-2.5 px-2.5 pb-1 pt-2 text-[10.5px] font-semibold uppercase tracking-[0.05em] text-faint"
      >
        <span className="w-6" />
        <span className="min-w-0 flex-1">{title === "Tags" ? "Tag" : "Lab"}</span>
        <span className="w-20">Trend</span>
        <span className="w-[76px] whitespace-nowrap text-right">In / related</span>
        <span className="w-16 whitespace-nowrap text-right">Not in it</span>
      </div>
      {loading ? (
        <div className="flex flex-col gap-2 p-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-7 animate-pulse rounded bg-surface-2" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="px-2.5 py-6 text-center text-sm text-muted">
          {title === "Tags" ? "No tags among the related papers yet." : "No labs among the related papers yet."}
        </p>
      ) : (
        <ul onMouseLeave={() => onHover(null)}>
          {items.map((it, i) => {
            const f = { kind: it.kind, key: it.key };
            const name = facetName(f);
            const on = picked?.kind === it.kind && picked.key === it.key;
            const sp = sparkPath(it.series);
            const divider = i > 0 && items[i - 1].followed && !it.followed;
            return (
              <li
                key={it.key}
                onMouseEnter={() => onHover(f)}
                className={cn(
                  "flex min-h-10 items-center gap-2.5 rounded-control px-2.5",
                  on && "bg-accent-weak",
                  divider && "mt-1 border-t border-border pt-1",
                )}
              >
                <button
                  type="button"
                  aria-pressed={it.followed}
                  aria-label={`${it.followed ? "Stop following" : "Follow"} ${name} in this project`}
                  title={`${it.followed ? "Stop following" : "Follow"} ${name} in this project`}
                  onClick={() => onFollow(f, !it.followed)}
                  className={cn(
                    "grid h-6 w-6 shrink-0 place-items-center rounded-control transition hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    it.followed ? "text-accent" : "text-faint",
                  )}
                >
                  <Star size={14} fill={it.followed ? "currentColor" : "none"} aria-hidden />
                </button>
                <button
                  type="button"
                  aria-pressed={on}
                  aria-label={`${name}: ${it.inCount} in the project of ${it.related} related. Filter the list.`}
                  onClick={() => onPick(on ? null : f)}
                  onFocus={() => onHover(f)}
                  className={cn(
                    "min-w-0 flex-1 truncate rounded-control text-left text-[13px] text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    it.kind === "tag" && "font-mono",
                  )}
                >
                  {name}
                </button>
                <svg width="80" height="22" viewBox="0 0 100 22" preserveAspectRatio="none" aria-hidden className="shrink-0 overflow-visible">
                  <path d={sp.area} fill="var(--accent-weak)" />
                  <path
                    d={sp.line}
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth={1.6}
                    strokeLinejoin="round"
                    vectorEffect="non-scaling-stroke"
                  />
                </svg>
                <span className="w-[76px] shrink-0 text-right text-[13px] tabular-nums">
                  <span className="font-semibold text-fg">{it.inCount}</span>
                  <span className="text-faint"> / {it.related}</span>
                </span>
                <span className="w-16 shrink-0 text-right">
                  {it.gap > 0 ? (
                    <button
                      type="button"
                      onClick={() => onGap(f)}
                      aria-label={`See the ${it.gap} related papers ${it.kind === "tag" ? `tagged ${it.key}` : `from the ${name}`} that are not in the project`}
                      className="inline-flex items-center gap-0.5 rounded-control px-1 text-[13px] font-semibold tabular-nums text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      {it.gap}
                      <ChevronRight size={12} aria-hidden />
                    </button>
                  ) : (
                    <span className="text-[13px] tabular-nums text-faint">0</span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-auto px-2.5 pb-1 pt-2.5 text-[11.5px] leading-snug text-faint">{foot}</p>
    </div>
  );
}
