import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { usePaperModal } from "@/components/PaperModal";
import { useTheme } from "@/components/ThemeProvider";
import { fetchMap } from "@/lib/api";
import type { MapPoint } from "@/lib/types";
import { useAppContext } from "@/routes/Layout";

/* Ordinal single-hue (blue) ramps, oldest → newest. Newest is the most
 * prominent step against each surface; both ramps validated (lightness
 * monotone, ΔL gaps, ≥2:1 surface contrast) against the app's surfaces. */
const YEAR_RAMP_LIGHT = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"];
const YEAR_RAMP_DARK = ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"];
const UNKNOWN_LIGHT = "#c4c8d0";
const UNKNOWN_DARK = "#4b5160";

const W = 800;
const H = 560;
const PAD = 36;

interface YearBin {
  label: string;
  color: string;
  contains: (year: number) => boolean;
}

/** Up to ramp.length equal-width year bins over the data's range. */
function makeYearBins(years: number[], ramp: string[]): YearBin[] {
  const distinct = [...new Set(years)].sort((a, b) => a - b);
  if (distinct.length === 0) return [];
  if (distinct.length <= ramp.length) {
    // One bin per year; use the ramp's most-recent-first end so the newest
    // year always gets the most prominent step.
    const steps = ramp.slice(ramp.length - distinct.length);
    return distinct.map((y, i) => ({
      label: String(y),
      color: steps[i],
      contains: (year) => year === y,
    }));
  }
  const min = distinct[0];
  const max = distinct[distinct.length - 1];
  const width = (max - min + 1) / ramp.length;
  return ramp.map((color, i) => {
    const lo = Math.floor(min + i * width);
    const hi = i === ramp.length - 1 ? max : Math.floor(min + (i + 1) * width) - 1;
    return {
      label: lo === hi ? String(lo) : `${lo}–${hi}`,
      color,
      contains: (year) => year >= lo && year <= hi,
    };
  });
}

export default function MapView() {
  const { team } = useAppContext();
  const { data, isLoading, error } = useQuery({
    queryKey: ["map", team.id],
    queryFn: () => fetchMap(team.id),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-8">
      <div>
        <h1 className="text-lg font-semibold">Map</h1>
        <p className="text-sm text-muted">
          Your lab’s papers, laid out by meaning — nearby papers are semantically similar.
        </p>
      </div>

      {isLoading && (
        <p className="text-sm text-muted">Computing the map… (first load can take a moment)</p>
      )}
      {error && <p className="text-sm text-danger">Couldn’t load the map.</p>}
      {data && data.points.length === 0 && (
        <p className="text-sm text-muted">
          {data.total === 0
            ? "No papers yet — post some first."
            : "No papers are embedded yet — embeddings are computed shortly after posting (or via the backfill script)."}
        </p>
      )}
      {data && data.points.length > 0 && <Scatter points={data.points} />}
      {data && data.points.length > 0 && data.embedded < data.total && (
        <p className="text-xs text-muted">
          Showing {data.embedded} of {data.total} papers — the rest are awaiting embedding.
        </p>
      )}
    </div>
  );
}

function Scatter({ points }: { points: MapPoint[] }) {
  const { theme } = useTheme();
  const { openPaper } = usePaperModal();
  const [hover, setHover] = useState<MapPoint | null>(null);

  const ramp = theme === "dark" ? YEAR_RAMP_DARK : YEAR_RAMP_LIGHT;
  const unknown = theme === "dark" ? UNKNOWN_DARK : UNKNOWN_LIGHT;

  const bins = useMemo(
    () => makeYearBins(points.map((p) => p.year).filter((y): y is number => y != null), ramp),
    [points, ramp],
  );
  const colorOf = (p: MapPoint) =>
    p.year == null ? unknown : (bins.find((b) => b.contains(p.year!))?.color ?? unknown);

  // Scale UMAP coordinates into the padded viewBox.
  const scaled = useMemo(() => {
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
    const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
    const sx = (x: number) => (x1 === x0 ? W / 2 : PAD + ((x - x0) / (x1 - x0)) * (W - 2 * PAD));
    const sy = (y: number) => (y1 === y0 ? H / 2 : PAD + ((y1 - y) / (y1 - y0)) * (H - 2 * PAD));
    return points.map((p) => ({ ...p, px: sx(p.x), py: sy(p.y) }));
  }, [points]);

  const hovered = hover && scaled.find((p) => p.paper_id === hover.paper_id);

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      {bins.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
          {bins.map((b) => (
            <span key={b.label} className="flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: b.color }}
              />
              {b.label}
            </span>
          ))}
          {points.some((p) => p.year == null) && (
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: unknown }}
              />
              year unknown
            </span>
          )}
        </div>
      )}

      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block h-auto w-full"
          role="img"
          aria-label="Semantic map of the lab's papers"
          onMouseLeave={() => setHover(null)}
        >
          {scaled.map((p) => (
            <g key={p.paper_id}>
              <circle
                cx={p.px}
                cy={p.py}
                r={hover?.paper_id === p.paper_id ? 7 : 5}
                fill={colorOf(p)}
                stroke="var(--surface)"
                strokeWidth={1.5}
              />
              {/* Hit target larger than the mark. */}
              <circle
                cx={p.px}
                cy={p.py}
                r={11}
                fill="transparent"
                className="cursor-pointer"
                role="button"
                tabIndex={0}
                aria-label={p.title ?? "Untitled paper"}
                onMouseEnter={() => setHover(p)}
                onFocus={() => setHover(p)}
                onBlur={() => setHover(null)}
                onClick={() => openPaper(p.paper_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") openPaper(p.paper_id);
                }}
              />
            </g>
          ))}
        </svg>

        {hovered && (
          <div
            className="pointer-events-none absolute z-10 max-w-64 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs shadow-sm"
            style={{
              left: `${(hovered.px / W) * 100}%`,
              top: `${(hovered.py / H) * 100}%`,
              transform: `translate(${hovered.px > W / 2 ? "calc(-100% - 10px)" : "10px"}, -50%)`,
            }}
          >
            <div className="font-medium text-fg">{hovered.title ?? "Untitled"}</div>
            {(hovered.venue || hovered.year) && (
              <div className="mt-0.5 font-mono text-muted">
                {[hovered.venue, hovered.year].filter(Boolean).join(" · ")}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
