import { type FormEvent, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { usePaperModal } from "@/components/PaperModal";
import { useTheme } from "@/components/ThemeProvider";
import { Input } from "@/components/ui/input";
import { fetchOverview, semanticSearch } from "@/lib/api";
import type { Cluster, OverviewPoint } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/* Validated categorical palette (clusters, venues) and sequential year ramp —
 * both stepped separately for light/dark surfaces (see dataviz palette). */
const CATEGORICAL_LIGHT = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"];
const CATEGORICAL_DARK = ["#3987e5", "#199e70", "#c98500", "#008300", "#9085e9", "#e66767", "#d55181", "#d95926"];
const YEAR_RAMP_LIGHT = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"];
const YEAR_RAMP_DARK = ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"];
const OTHER_LIGHT = "#c4c8d0";
const OTHER_DARK = "#4b5160";

const W = 760;
const H = 520;
const PAD = 28;

type ColorMode = "cluster" | "year" | "venue";
type SizeMode = "uniform" | "engagement";

export default function MapView() {
  const { team } = useAppContext();
  const { data, isLoading, error } = useQuery({
    queryKey: ["overview", team.id],
    queryFn: () => fetchOverview(team.id),
    staleTime: 5 * 60 * 1000,
  });

  const [colorBy, setColorBy] = useState<ColorMode>("cluster");
  const [sizeBy, setSizeBy] = useState<SizeMode>("uniform");
  const [rawQuery, setRawQuery] = useState("");
  const [matchIds, setMatchIds] = useState<Set<string> | null>(null);
  const [searching, setSearching] = useState(false);

  async function runFilter(e: FormEvent) {
    e.preventDefault();
    const q = rawQuery.trim();
    if (!q) {
      setMatchIds(null);
      return;
    }
    setSearching(true);
    try {
      const hits = await semanticSearch(q, team.id, 50);
      setMatchIds(new Set(hits.map((h) => h.post.papers.id)));
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-display font-bold tracking-tight text-fg">Overview</h1>
        <p className="mt-1.5 text-sm text-muted">
          Your lab’s papers by meaning, plus themes and trends across what you’ve shared.
        </p>
      </div>

      {isLoading && <p className="text-sm text-muted">Computing the overview… (first load can take a moment)</p>}
      {error && <p className="text-sm text-danger">Couldn’t load the overview.</p>}

      {data && data.points.length === 0 && (
        <p className="text-sm text-muted">
          {data.total === 0
            ? "No papers yet — post some first."
            : "No papers are embedded yet — embeddings compute shortly after posting."}
        </p>
      )}

      {data && data.points.length > 0 && (
        <>
          {/* controls */}
          <div className="flex flex-wrap items-center gap-3">
            <Segmented
              label="Color"
              value={colorBy}
              onChange={(v) => setColorBy(v as ColorMode)}
              options={[
                ["cluster", "Theme"],
                ["year", "Year"],
                ["venue", "Venue"],
              ]}
            />
            <Segmented
              label="Size"
              value={sizeBy}
              onChange={(v) => setSizeBy(v as SizeMode)}
              options={[
                ["uniform", "Uniform"],
                ["engagement", "Engagement"],
              ]}
            />
            <form onSubmit={runFilter} className="relative min-w-[200px] flex-1">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <Input
                value={rawQuery}
                onChange={(e) => setRawQuery(e.target.value)}
                placeholder="Filter by topic, then Enter…"
                className="pl-9"
              />
            </form>
            {matchIds && (
              <button
                type="button"
                onClick={() => {
                  setRawQuery("");
                  setMatchIds(null);
                }}
                className="text-xs text-muted hover:text-fg"
              >
                Clear filter ({matchIds.size})
              </button>
            )}
          </div>

          <Scatter
            points={data.points}
            clusters={data.clusters}
            colorBy={colorBy}
            sizeBy={sizeBy}
            matchIds={searching ? null : matchIds}
          />
          {data.embedded < data.total && (
            <p className="-mt-2 text-xs text-faint">
              Showing {data.embedded} of {data.total} papers — the rest are awaiting embedding.
            </p>
          )}

          {/* stats */}
          <div className="grid gap-4 sm:grid-cols-2">
            <StatCard title="Posts over time">
              <Bars data={data.stats.over_time.map((d) => ({ label: d.month, value: d.count }))} />
            </StatCard>
            <StatCard title="Papers by year">
              <Bars data={data.stats.by_year.map((d) => ({ label: String(d.year), value: d.count }))} />
            </StatCard>
            <StatCard title="Top venues">
              <Bars data={data.stats.by_venue.map((d) => ({ label: d.venue, value: d.count }))} horizontal />
            </StatCard>
            <StatCard title="Most-shared labs (last author)">
              <Bars data={data.stats.by_lab.map((d) => ({ label: d.lab, value: d.count }))} horizontal />
            </StatCard>
          </div>
        </>
      )}
    </div>
  );
}

function Segmented({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-muted">{label}</span>
      <div className="inline-flex overflow-hidden rounded-control border border-border">
        {options.map(([v, lbl]) => (
          <button
            key={v}
            type="button"
            aria-pressed={value === v}
            onClick={() => onChange(v)}
            className={cn(
              "px-2.5 py-1.5 text-xs font-medium transition",
              value === v ? "bg-surface-2 text-fg" : "text-muted hover:text-fg",
            )}
          >
            {lbl}
          </button>
        ))}
      </div>
    </div>
  );
}

function Scatter({
  points,
  clusters,
  colorBy,
  sizeBy,
  matchIds,
}: {
  points: OverviewPoint[];
  clusters: Cluster[];
  colorBy: ColorMode;
  sizeBy: SizeMode;
  matchIds: Set<string> | null;
}) {
  const { theme } = useTheme();
  const { openPaper } = usePaperModal();
  const [hover, setHover] = useState<OverviewPoint | null>(null);
  const [activeCluster, setActiveCluster] = useState<number | null>(null);

  const cat = theme === "dark" ? CATEGORICAL_DARK : CATEGORICAL_LIGHT;
  const yearRamp = theme === "dark" ? YEAR_RAMP_DARK : YEAR_RAMP_LIGHT;
  const other = theme === "dark" ? OTHER_DARK : OTHER_LIGHT;

  // Legend + color function depend on the color mode.
  const { colorOf, legend } = useMemo(() => {
    if (colorBy === "cluster") {
      const byId = new Map(clusters.map((c) => [c.id, c]));
      return {
        colorOf: (p: OverviewPoint) => cat[p.cluster % cat.length],
        legend: clusters.map((c) => ({
          key: c.id,
          color: cat[c.id % cat.length],
          label: c.label,
          sub: `${c.size}`,
          title: byId.get(c.id)?.description,
        })),
      };
    }
    if (colorBy === "year") {
      const years = points.map((p) => p.year).filter((y): y is number => y != null);
      const bins = yearBins(years, yearRamp);
      return {
        colorOf: (p: OverviewPoint) =>
          p.year == null ? other : (bins.find((b) => b.contains(p.year!))?.color ?? other),
        legend: bins.map((b) => ({ key: b.label, color: b.color, label: b.label, sub: undefined, title: undefined })),
      };
    }
    // venue: top 7 + Other
    const counts = new Map<string, number>();
    for (const p of points) if (p.venue) counts.set(p.venue, (counts.get(p.venue) ?? 0) + 1);
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 7).map(([v]) => v);
    const color = new Map(top.map((v, i) => [v, cat[i]]));
    return {
      colorOf: (p: OverviewPoint) => (p.venue && color.has(p.venue) ? color.get(p.venue)! : other),
      legend: [
        ...top.map((v) => ({ key: v, color: color.get(v)!, label: v, sub: undefined, title: undefined })),
        { key: "__other", color: other, label: "Other", sub: undefined, title: undefined },
      ],
    };
  }, [colorBy, clusters, points, cat, yearRamp, other]);

  const maxEng = Math.max(1, ...points.map((p) => p.reactions + p.comments));
  const radiusOf = (p: OverviewPoint) =>
    sizeBy === "engagement" ? 3.5 + 6 * Math.sqrt((p.reactions + p.comments) / maxEng) : 5;

  const scaled = useMemo(() => {
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
    const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
    const sx = (x: number) => (x1 === x0 ? W / 2 : PAD + ((x - x0) / (x1 - x0)) * (W - 2 * PAD));
    const sy = (y: number) => (y1 === y0 ? H / 2 : PAD + ((y1 - y) / (y1 - y0)) * (H - 2 * PAD));
    return points.map((p) => ({ ...p, px: sx(p.x), py: sy(p.y) }));
  }, [points]);

  const dimmed = (p: OverviewPoint) =>
    (matchIds !== null && !matchIds.has(p.paper_id)) ||
    (activeCluster !== null && colorBy === "cluster" && p.cluster !== activeCluster);

  const hovered = hover && scaled.find((p) => p.paper_id === hover.paper_id);

  return (
    <div className="rounded-card border border-border bg-surface p-4">
      {/* legend */}
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted">
        {legend.map((l) => (
          <button
            key={l.key}
            type="button"
            title={l.title}
            onClick={() =>
              colorBy === "cluster" &&
              setActiveCluster(activeCluster === Number(l.key) ? null : Number(l.key))
            }
            className={cn(
              "flex items-center gap-1.5",
              colorBy === "cluster" && "hover:text-fg",
              activeCluster !== null && colorBy === "cluster" && activeCluster !== Number(l.key) && "opacity-40",
            )}
          >
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: l.color }} />
            {l.label}
            {l.sub && <span className="font-mono text-faint">{l.sub}</span>}
          </button>
        ))}
      </div>

      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block h-auto w-full"
          role="img"
          aria-label="Semantic map of the lab's papers"
          onMouseLeave={() => setHover(null)}
        >
          {scaled.map((p) => (
            <circle
              key={p.paper_id}
              cx={p.px}
              cy={p.py}
              r={hover?.paper_id === p.paper_id ? radiusOf(p) + 2 : radiusOf(p)}
              fill={colorOf(p)}
              fillOpacity={dimmed(p) ? 0.12 : 0.92}
              stroke="var(--surface)"
              strokeWidth={1.25}
              className="cursor-pointer"
              onMouseEnter={() => setHover(p)}
              onClick={() => openPaper(p.paper_id)}
            />
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
              <div className="mt-0.5 font-mono text-faint">
                {[hovered.venue, hovered.year].filter(Boolean).join(" · ")}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

interface YearBin {
  label: string;
  color: string;
  contains: (year: number) => boolean;
}

function yearBins(years: number[], ramp: string[]): YearBin[] {
  const distinct = [...new Set(years)].sort((a, b) => a - b);
  if (distinct.length === 0) return [];
  if (distinct.length <= ramp.length) {
    const steps = ramp.slice(ramp.length - distinct.length);
    return distinct.map((y, i) => ({ label: String(y), color: steps[i], contains: (yy) => yy === y }));
  }
  const min = distinct[0];
  const max = distinct[distinct.length - 1];
  const width = (max - min + 1) / ramp.length;
  return ramp.map((color, i) => {
    const lo = Math.floor(min + i * width);
    const hi = i === ramp.length - 1 ? max : Math.floor(min + (i + 1) * width) - 1;
    return { label: lo === hi ? String(lo) : `${lo}–${hi}`, color, contains: (yy) => yy >= lo && yy <= hi };
  });
}

function StatCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="mb-3 text-eyebrow font-bold uppercase tracking-eyebrow text-muted">{title}</div>
      {children}
    </div>
  );
}

/** A minimal bar chart in inline SVG (vertical) or CSS rows (horizontal). */
function Bars({ data, horizontal = false }: { data: { label: string; value: number }[]; horizontal?: boolean }) {
  if (data.length === 0) return <p className="text-xs text-faint">No data.</p>;
  const max = Math.max(...data.map((d) => d.value));

  if (horizontal) {
    return (
      <div className="flex flex-col gap-1.5">
        {data.map((d) => (
          <div key={d.label} className="flex items-center gap-2 text-xs">
            <span className="w-28 shrink-0 truncate text-muted" title={d.label}>
              {d.label}
            </span>
            <div className="h-3 flex-1 overflow-hidden rounded bg-surface-2">
              <div className="h-full rounded bg-accent" style={{ width: `${(d.value / max) * 100}%` }} />
            </div>
            <span className="w-6 shrink-0 text-right font-mono tabular-nums text-faint">{d.value}</span>
          </div>
        ))}
      </div>
    );
  }

  const bw = 100 / data.length;
  return (
    <div>
      <svg viewBox="0 0 100 40" className="block h-24 w-full" preserveAspectRatio="none">
        {data.map((d, i) => {
          const h = (d.value / max) * 36;
          return (
            <rect
              key={d.label}
              x={i * bw + bw * 0.15}
              y={38 - h}
              width={bw * 0.7}
              height={h}
              rx={0.6}
              className="fill-accent"
            />
          );
        })}
      </svg>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-faint">
        <span>{data[0]?.label}</span>
        {data.length > 1 && <span>{data[data.length - 1]?.label}</span>}
      </div>
    </div>
  );
}
