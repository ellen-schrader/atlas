import { useMemo, useRef } from "react";

import { useElementWidth } from "@/hooks/useElementWidth";
import { cn } from "@/lib/utils";

/** How a dot is drawn: in the project (filled), suggested (ringed; new ones
 *  bolder), or the rest of the library (faint). */
export type DotKind = "in" | "suggested" | "new" | "other";

export interface Dot {
  id: string;
  year: number;
  similarity: number;
  kind: DotKind;
}

const PAD = { top: 12, right: 14, bottom: 24, left: 36 };

/** A stable sideways nudge in (-0.38, 0.38) years, so a year's papers spread
 *  into a column instead of stacking on one x. */
function jitter(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return (((h >>> 0) % 1000) / 1000 - 0.5) * 0.76;
}

/** Closeness × year: x is the publication year, y the similarity to the
 *  closest paper in the project. A dashed line marks "suggested above this";
 *  the shaded top-right corner is recent and close. The list beside it carries
 *  the same papers, so the chart itself is an image to screen readers. */
export function ClosenessChart({
  dots,
  cutoff,
  height = 300,
  mini = false,
  lit,
  hovered,
  selected,
  onHover,
  onSelect,
  label,
}: {
  dots: Dot[];
  cutoff: number | null;
  height?: number;
  /** The index cards' small version: no axes, no interaction. */
  mini?: boolean;
  /** When set, dots outside it fade (a tag or lab is hovered or picked). */
  lit?: ReadonlySet<string> | null;
  hovered?: string | null;
  selected?: string | null;
  onHover?: (id: string | null) => void;
  onSelect?: (id: string) => void;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const width = useElementWidth(ref);
  const pad = mini ? { top: 4, right: 4, bottom: 4, left: 4 } : PAD;

  const scale = useMemo(() => {
    const years = dots.map((d) => d.year);
    const sims = dots.map((d) => d.similarity);
    const thisYear = new Date().getFullYear();
    const x0 = Math.min(thisYear - 6, ...years);
    const x1 = Math.max(thisYear, ...years);
    const y0 = Math.max(-1, Math.floor(Math.min(0.2, ...sims, cutoff ?? 1) * 10) / 10);
    const y1 = 1;
    const w = Math.max(0, width - pad.left - pad.right);
    const h = Math.max(0, height - pad.top - pad.bottom);
    return {
      x0,
      x1,
      y0,
      y1,
      x: (year: number) => pad.left + ((year - x0 + 0.5) / (x1 - x0 + 1)) * w,
      y: (sim: number) => pad.top + (1 - (sim - y0) / (y1 - y0)) * h,
    };
  }, [dots, cutoff, width, height, pad.left, pad.right, pad.top, pad.bottom]);

  // Faint ones first, so the project's own and the suggestions draw on top.
  const order: Record<DotKind, number> = { other: 0, suggested: 1, new: 2, in: 3 };
  const sorted = [...dots].sort((a, b) => order[a.kind] - order[b.kind]);
  const yearTicks: number[] = [];
  const step = Math.max(1, Math.ceil((scale.x1 - scale.x0 + 1) / 7));
  for (let yr = scale.x1; yr >= scale.x0; yr -= step) yearTicks.unshift(yr);
  const simTicks: number[] = [];
  for (let t = Math.ceil(scale.y0 * 5) / 5; t <= 1.0001; t += 0.2) simTicks.push(Math.round(t * 10) / 10);

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={label}
          className={cn("block", !mini && "select-none")}
          onMouseLeave={() => onHover?.(null)}
        >
          {/* recent and close */}
          {cutoff != null && (
            <rect
              x={scale.x(scale.x1 - 2) - 4}
              y={pad.top}
              width={Math.max(0, width - pad.right - scale.x(scale.x1 - 2) + 4)}
              height={Math.max(0, scale.y(Math.max(cutoff, scale.y0)) - pad.top)}
              fill="var(--accent-weak)"
              opacity={0.6}
              rx={6}
            />
          )}
          {!mini &&
            simTicks.map((t) => (
              <g key={t}>
                <line
                  x1={pad.left}
                  x2={width - pad.right}
                  y1={scale.y(t)}
                  y2={scale.y(t)}
                  stroke="var(--border)"
                />
                <text
                  x={pad.left - 8}
                  y={scale.y(t)}
                  dy="0.32em"
                  textAnchor="end"
                  className="fill-faint text-[10px] tabular-nums"
                >
                  {t.toFixed(1)}
                </text>
              </g>
            ))}
          {!mini &&
            yearTicks.map((yr) => (
              <text
                key={yr}
                x={scale.x(yr)}
                y={height - 6}
                textAnchor="middle"
                className="fill-faint text-[10px] tabular-nums"
              >
                {yr}
              </text>
            ))}
          {cutoff != null && cutoff > scale.y0 && (
            <g>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={scale.y(cutoff)}
                y2={scale.y(cutoff)}
                stroke="var(--accent)"
                strokeDasharray="4 4"
                strokeWidth={1.2}
              />
              {!mini && (
                <text
                  x={pad.left + 6}
                  y={scale.y(cutoff) - 5}
                  className="fill-accent text-[10px] font-semibold"
                >
                  Suggested above this
                </text>
              )}
            </g>
          )}
          {sorted.map((d) => {
            const cx = scale.x(d.year + jitter(d.id));
            const cy = scale.y(d.similarity);
            const dim = lit != null && !lit.has(d.id);
            const focus = d.id === hovered || d.id === selected;
            const r = mini ? (d.kind === "other" ? 1.6 : 2.6) : d.kind === "other" ? 2.6 : 4.2;
            const common = {
              cx,
              cy,
              r: focus ? r + 2 : r,
              opacity: dim ? 0.18 : 1,
              style: { cursor: mini || !onSelect ? undefined : "pointer" },
              onMouseEnter: mini ? undefined : () => onHover?.(d.id),
              onClick: mini ? undefined : () => onSelect?.(d.id),
            };
            if (d.kind === "in")
              return <circle key={d.id} {...common} fill="var(--accent)" stroke="var(--surface)" />;
            if (d.kind === "other")
              return <circle key={d.id} {...common} fill="var(--ch-off)" opacity={dim ? 0.12 : 0.55} />;
            return (
              <circle
                key={d.id}
                {...common}
                fill="var(--surface)"
                stroke="var(--accent)"
                strokeWidth={d.kind === "new" ? 2.4 : 1.4}
              />
            );
          })}
        </svg>
      )}
    </div>
  );
}

/** The legend under the full chart. */
export function ChartLegend({ className }: { className?: string }) {
  const item = (dot: React.ReactNode, text: string) => (
    <span className="inline-flex items-center gap-1.5">
      <svg width="10" height="10" aria-hidden>
        {dot}
      </svg>
      {text}
    </span>
  );
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted", className)}>
      {item(<circle cx="5" cy="5" r="4" fill="var(--accent)" />, "In the project")}
      {item(<circle cx="5" cy="5" r="3.6" fill="none" stroke="var(--accent)" strokeWidth="1.4" />, "Suggested")}
      {item(<circle cx="5" cy="5" r="3.4" fill="none" stroke="var(--accent)" strokeWidth="2.4" />, "New since you looked")}
      {item(<circle cx="5" cy="5" r="2.6" fill="var(--ch-off)" />, "Rest of the library")}
    </div>
  );
}
