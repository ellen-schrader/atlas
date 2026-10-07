import { useMemo } from "react";

import { SectionHeading } from "@/components/home/HomeSection";
import { formatChange } from "@/components/home/Trending";
import type { TagWeek, TrendingTag } from "@/hooks/useTrends";
import { cn } from "@/lib/utils";

const W = 300;
const H = 110;

/** A tag's data channel, from its name: colour follows the entity, never its
 *  rank, so a tag keeps its colour when the ranking shifts. Collisions are
 *  harmless — only one band is ever coloured at a time. */
export function tagChannel(tag: string): string {
  let h = 0;
  for (const ch of tag) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `var(--ch-${(h % 6) + 1})`;
}

/** Stacked weekly areas for Trending's tags. Monochrome until a band (or its
 *  Trending row) is hovered/tapped; then that band takes its colour and the
 *  readout names it, with the SAME numbers as the Trending row. The chart only
 *  contributes the shape. */
export function TagVolume({
  tags,
  series,
  loading,
  hoveredTag,
  onHoverTag,
  touch,
  className,
}: {
  /** Trending's rows, in rank order: the stack order and the readout's source. */
  tags: TrendingTag[];
  series: TagWeek[];
  loading: boolean;
  hoveredTag: string | null;
  onHoverTag: (tag: string | null) => void;
  touch: boolean;
  className?: string;
}) {
  const { weeks, bands } = useMemo(() => stack(tags, series), [tags, series]);
  const hovered = tags.find((t) => t.tag === hoveredTag) ?? null;
  const topRiser = [...tags].sort((a, b) => b.n - b.prev - (a.n - a.prev))[0];
  const label = topRiser
    ? `Papers per week by tag over the last 12 weeks. Fastest rising: ${topRiser.tag}, ${topRiser.n} papers in 30 days (${formatChange(topRiser.n, topRiser.prev)}).`
    : "Papers per week by tag over the last 12 weeks.";

  return (
    <section className={cn("flex min-w-0 flex-col", className)}>
      <SectionHeading
        title="Tag volume"
        right={<span className="truncate text-[11px] text-muted">papers per week · last 12 weeks</span>}
      />
      <div className="flex flex-1 flex-col rounded-card border border-border bg-surface p-4">
        <div className="flex h-5 items-center gap-2 text-meta" aria-live="polite">
          {hovered ? (
            <>
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{ background: tagChannel(hovered.tag) }}
                aria-hidden
              />
              <span className="truncate font-mono text-fg">{hovered.tag}</span>
              <span className="shrink-0 text-muted">
                {hovered.n} in 30 days · {formatChange(hovered.n, hovered.prev)}
              </span>
            </>
          ) : (
            <span className="text-muted">
              {touch ? "Tap the chart to see a tag" : "Hover the chart to see a tag"}
            </span>
          )}
        </div>

        <div className="relative mt-3 min-h-[130px] flex-1">
          {loading ? (
            <div className="absolute inset-0 animate-pulse rounded-md bg-surface-2" />
          ) : bands.length === 0 ? (
            <p className="absolute inset-0 grid place-items-center text-sm text-muted">
              Not enough tagged papers yet.
            </p>
          ) : (
            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              role="img"
              aria-label={label}
              className="absolute inset-0 h-full w-full"
              onMouseLeave={() => !touch && onHoverTag(null)}
            >
              {bands.map((b, i) => {
                const on = hoveredTag === b.tag;
                const fill = hoveredTag
                  ? on
                    ? tagChannel(b.tag)
                    : "var(--surface-3)"
                  : i % 2 === 0
                    ? "var(--ch-off)"
                    : "var(--border-strong)";
                return (
                  <path
                    key={b.tag}
                    d={b.path}
                    fill={fill}
                    fillOpacity={on ? 0.9 : 1}
                    stroke="var(--surface)"
                    strokeWidth={1}
                    vectorEffect="non-scaling-stroke"
                    className="cursor-pointer transition-[fill] duration-150"
                    onMouseEnter={() => !touch && onHoverTag(b.tag)}
                    onClick={() => onHoverTag(on && touch ? null : b.tag)}
                  />
                );
              })}
            </svg>
          )}
        </div>

        {weeks.length > 0 && (
          <div className="mt-2 flex justify-between font-mono text-[10.5px] text-faint" aria-hidden>
            <span>{weekLabel(weeks[0])}</span>
            <span>{weekLabel(weeks[Math.floor((weeks.length - 1) / 2)])}</span>
            <span>{weekLabel(weeks[weeks.length - 1])}</span>
          </div>
        )}
      </div>
    </section>
  );
}

function weekLabel(iso: string): string {
  // Date-only ISO strings parse as UTC; format in UTC so "Oct 6" stays Oct 6.
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** Stack the weekly counts in Trending's order (largest at the bottom) and turn
 *  each band into an SVG path in the 300×110 viewBox. */
function stack(tags: TrendingTag[], series: TagWeek[]) {
  const weeks = [...new Set(series.map((s) => s.week))].sort();
  if (weeks.length < 2) return { weeks, bands: [] as { tag: string; path: string }[] };
  const byTag = new Map<string, Map<string, number>>();
  for (const s of series) {
    if (!byTag.has(s.tag)) byTag.set(s.tag, new Map());
    byTag.get(s.tag)!.set(s.week, s.n);
  }
  const order = tags.map((t) => t.tag).filter((t) => byTag.has(t));
  const base = weeks.map(() => 0);
  const layers = order.map((tag) => {
    const lower = [...base];
    weeks.forEach((w, i) => (base[i] += byTag.get(tag)!.get(w) ?? 0));
    return { tag, lower, upper: [...base] };
  });
  const max = Math.max(1, ...base);
  // A little headroom so the top band doesn't touch the card's edge.
  const y = (v: number) => H - (v / max) * (H - 6);
  const x = (i: number) => (i / (weeks.length - 1)) * W;
  const bands = layers.map(({ tag, lower, upper }) => {
    const top = upper.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`);
    const bottom = lower
      .map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`)
      .reverse();
    return { tag, path: `M${top.join("L")}L${bottom.join("L")}Z` };
  });
  return { weeks, bands };
}
