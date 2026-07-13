import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Loader2, Search, X } from "lucide-react";

import { usePaperModal } from "@/components/PaperModal";
import { Input } from "@/components/ui/input";
import { fetchOverview, fetchSimilarity, isTransientApiError } from "@/lib/api";
import { markFor, markPath, usePalette } from "@/lib/palette";
import type { Cluster, OverviewData, OverviewPoint } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

const W = 760;
const H = 520;
const PAD = 28;

type ColorMode = "cluster" | "year" | "venue" | "relevance";
type SizeMode = "uniform" | "engagement";
type BarHover = { kind: "year" | "venue" | "lab"; value: string } | null;

// Fixed pseudo-scatter for the loading skeleton (percent coordinates).
const LOADING_DOTS = [
  [18, 32], [27, 61], [36, 22], [42, 74], [48, 45], [55, 28],
  [61, 66], [70, 38], [78, 57], [85, 27], [64, 82], [24, 44],
] as const;

// The layout computes in a couple of seconds when the API is warm, but the
// first request after an idle spell also pays the machine's cold boot
// (~half a minute). Advance the message so a long wait reads as progress.
const LOADING_STAGES = [
  "Computing the map of your lab’s papers…",
  "Waking the paper service — it sleeps when nobody’s around…",
  "Still working. The first load after a quiet spell can take up to a minute.",
];

function MapLoadingSkeleton() {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const timers = [setTimeout(() => setStage(1), 6_000), setTimeout(() => setStage(2), 20_000)];
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <>
      {/* Mirror the loaded page (KPI strip → header → map card) so the panel
          barely moves when data lands. */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" aria-hidden>
        {Array.from({ length: 6 }, (_, i) => (
          <div
            key={i}
            className="h-[68px] animate-pulse rounded-card border border-border bg-surface-2"
          />
        ))}
      </div>
      <div className="h-5 w-16 animate-pulse rounded bg-surface-2" aria-hidden />
      <div className="rounded-card border border-border bg-surface p-4">
        <div className="relative w-full" style={{ aspectRatio: `${W} / ${H}` }} role="status">
          {LOADING_DOTS.map(([x, y], i) => (
            <span
              key={i}
              className="absolute h-2.5 w-2.5 animate-pulse rounded-full bg-fg/10"
              style={{ left: `${x}%`, top: `${y}%`, animationDelay: `${(i % 4) * 350}ms` }}
              aria-hidden
            />
          ))}
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            <Loader2 className="animate-spin text-muted" size={22} aria-hidden />
            <p className="max-w-sm px-6 text-center text-sm text-muted">{LOADING_STAGES[stage]}</p>
          </div>
        </div>
      </div>
    </>
  );
}

export default function MapView() {
  const { team } = useAppContext();
  const { data, isLoading, error } = useQuery({
    queryKey: ["overview", team.id],
    queryFn: () => fetchOverview(team.id),
    staleTime: 5 * 60 * 1000,
    // Cold-boot-aware retry comes from the QueryClient default (main.tsx).
  });

  const [colorBy, setColorBy] = useState<ColorMode>("cluster");
  const [sizeBy, setSizeBy] = useState<SizeMode>("uniform");
  const [showHulls, setShowHulls] = useState(true);
  const [rawQuery, setRawQuery] = useState("");
  const [topic, setTopic] = useState(""); // the submitted query, for the filter chip
  const [sims, setSims] = useState<Record<string, number> | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [labFilter, setLabFilter] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [activeCluster, setActiveCluster] = useState<number | null>(null);
  const [barHover, setBarHover] = useState<BarHover>(null);
  const { categorical: cat } = usePalette();

  async function runFilter(e: FormEvent) {
    e.preventDefault();
    const q = rawQuery.trim();
    if (!q) {
      clearQuery();
      return;
    }
    setSearching(true);
    setSearchError(null);
    try {
      setSims(await fetchSimilarity(q, team.id));
      setTopic(q);
      setColorBy("relevance"); // show the relevance heatmap immediately
    } catch (err) {
      // One attempt, no retry (imperative call): tell the user what happened
      // instead of a silently un-spinning search box.
      setSearchError(
        isTransientApiError(err)
          ? "The paper service is waking up — try the search again in a few seconds."
          : err instanceof Error
            ? err.message
            : "Search failed.",
      );
    } finally {
      setSearching(false);
    }
  }

  function clearQuery() {
    setRawQuery("");
    setTopic("");
    setSims(null);
    setSearchError(null);
    if (colorBy === "relevance") setColorBy("cluster");
  }

  function clearAll() {
    clearQuery();
    setLabFilter(null);
    setTagFilter(null);
    setActiveCluster(null);
  }

  const anyFilter = Boolean(sims || labFilter || tagFilter || activeCluster !== null);

  const points = data?.points ?? [];
  const labPapers = labFilter ? points.filter((p) => p.lab === labFilter) : [];
  const hasEngagement = points.some((p) => p.reactions + p.comments > 0);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-display font-serif font-semibold tracking-tight text-fg">Overview</h1>
        <p className="mt-1.5 text-sm text-muted">
          Your lab’s papers by meaning, plus themes and trends across what you’ve shared.
        </p>
      </div>

      {isLoading && <MapLoadingSkeleton />}
      {error && !data && (
        <p className="text-sm text-danger">
          {isTransientApiError(error)
            ? "Couldn’t load the overview — give it a moment and reload the page."
            : "Couldn’t load the overview."}{" "}
          {error instanceof Error && !isTransientApiError(error) ? error.message : null}
        </p>
      )}

      {data && points.length === 0 && (
        <p className="text-sm text-muted">
          {data.total === 0
            ? "No papers yet — post some first."
            : "No papers are embedded yet — embeddings compute shortly after posting."}
        </p>
      )}

      {data && points.length > 0 && (
        <>
          <KpiStrip data={data} />

          <SectionHeader>Map</SectionHeader>
          {/* controls */}
          <div className="flex flex-wrap items-center gap-3">
            <Segmented
              label="Color"
              value={colorBy}
              onChange={(v) => setColorBy(v as ColorMode)}
              options={[
                { value: "cluster", label: "Theme" },
                { value: "year", label: "Year" },
                { value: "venue", label: "Venue" },
                ...(sims ? [{ value: "relevance", label: "Relevance" }] : []),
              ]}
            />
            <Segmented
              label="Size"
              value={sizeBy}
              onChange={(v) => setSizeBy(v as SizeMode)}
              options={[
                {
                  value: "uniform",
                  label: "Uniform",
                  disabled: colorBy === "relevance",
                  title: colorBy === "relevance" ? "Size follows relevance in this mode" : undefined,
                },
                {
                  value: "engagement",
                  label: "Engagement",
                  disabled: !hasEngagement || colorBy === "relevance",
                  title:
                    colorBy === "relevance"
                      ? "Size follows relevance in this mode"
                      : hasEngagement
                        ? undefined
                        : "No reactions or comments yet",
                },
              ]}
            />
            <button
              type="button"
              aria-pressed={showHulls}
              onClick={() => setShowHulls((s) => !s)}
              className={cn(
                "rounded-control border px-2.5 py-1.5 text-xs font-medium transition",
                showHulls
                  ? "border-accent/50 bg-accent-weak text-accent"
                  : "border-border text-muted hover:text-fg",
              )}
            >
              Theme outlines
            </button>
            <form onSubmit={runFilter} className="relative min-w-[200px] flex-1">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <Input
                value={rawQuery}
                onChange={(e) => setRawQuery(e.target.value)}
                placeholder="Colour by relevance to a topic…"
                className="pl-9"
              />
            </form>
          </div>

          {searchError && <p className="-mt-2 text-xs text-danger">{searchError}</p>}

          {/* active filters — one place to see and clear everything */}
          {anyFilter && (
            <div className="-mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
              <span className="font-medium">Filters:</span>
              {sims && (
                <FilterChip onClear={clearQuery}>
                  Topic:{" "}
                  <span className="inline-block max-w-[160px] truncate align-bottom text-fg">{topic}</span>
                </FilterChip>
              )}
              {activeCluster !== null && (
                <FilterChip onClear={() => setActiveCluster(null)}>
                  Theme:{" "}
                  <span className="text-fg">
                    {data.clusters.find((c) => c.id === activeCluster)?.label ?? activeCluster}
                  </span>
                </FilterChip>
              )}
              {tagFilter && (
                <FilterChip onClear={() => setTagFilter(null)}>
                  Tag: <span className="font-mono text-fg">{tagFilter}</span>
                </FilterChip>
              )}
              {labFilter && (
                <FilterChip onClear={() => setLabFilter(null)}>
                  Lab: <span className="text-fg">{labFilter}</span>
                </FilterChip>
              )}
              <button type="button" onClick={clearAll} className="underline hover:text-fg">
                Clear all
              </button>
            </div>
          )}

          <Scatter
            points={points}
            clusters={data.clusters}
            colorBy={colorBy}
            sizeBy={sizeBy}
            showHulls={showHulls}
            sims={searching ? null : sims}
            labFilter={labFilter}
            tagFilter={tagFilter}
            activeCluster={activeCluster}
            setActiveCluster={setActiveCluster}
            barHover={barHover}
          />
          {data.embedded < data.total && (
            <p className="-mt-2 text-xs text-faint">
              Showing {data.embedded} of {data.total} papers — the rest are awaiting embedding.
            </p>
          )}

          {/* lab drill-down */}
          {labFilter && (
            <LabPapers lab={labFilter} papers={labPapers} onClear={() => setLabFilter(null)} />
          )}

          {/* trends */}
          <SectionHeader>Trends</SectionHeader>
          <Insights data={data} />
          <p className="-mt-1 text-xs text-faint">
            Hover a bar to highlight those papers on the map; click a theme, tag, or lab to filter.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <StatCard title="Themes">
              <ThemeBars
                clusters={data.clusters}
                cat={cat}
                active={activeCluster}
                onToggle={(id) => setActiveCluster(activeCluster === id ? null : id)}
              />
            </StatCard>
            <StatCard title="Top tags">
              <Bars
                horizontal
                data={data.stats.by_tag.slice(0, 10).map((d) => ({ label: d.tag, value: d.count }))}
                onClick={(label) => setTagFilter((cur) => (cur === label ? null : label))}
                activeLabel={tagFilter}
              />
            </StatCard>
            <StatCard title="Top venues">
              <Bars
                horizontal
                data={data.stats.by_venue.map((d) => ({ label: d.venue, value: d.count }))}
                onHover={(label) => setBarHover(label ? { kind: "venue", value: label } : null)}
              />
            </StatCard>
            <StatCard title="Most-shared labs (last author)">
              <Bars
                horizontal
                data={data.stats.by_lab.map((d) => ({ label: d.lab, value: d.count }))}
                onHover={(label) => setBarHover(label ? { kind: "lab", value: label } : null)}
                onClick={(label) => setLabFilter((cur) => (cur === label ? null : label))}
                activeLabel={labFilter}
              />
            </StatCard>
            <StatCard title="Shared over time">
              <Bars data={data.stats.over_time.map((d) => ({ label: fmtMonth(d.month), value: d.count }))} />
            </StatCard>
            <StatCard title="Publication year">
              <Bars
                data={groupYears(data.stats.by_year)}
                onHover={(label) => setBarHover(label ? { kind: "year", value: label } : null)}
              />
            </StatCard>
          </div>
        </>
      )}
    </div>
  );
}

function FilterChip({ children, onClear }: { children: ReactNode; onClear: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-chip border border-border bg-surface-2 px-2 py-0.5">
      {children}
      <button
        type="button"
        aria-label="Remove filter"
        onClick={onClear}
        className="text-muted transition hover:text-danger"
      >
        <X size={11} />
      </button>
    </span>
  );
}

interface SegOption {
  value: string;
  label: string;
  disabled?: boolean;
  title?: string;
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
  options: SegOption[];
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-muted">{label}</span>
      <div className="inline-flex overflow-hidden rounded-control border border-border">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={value === o.value}
            disabled={o.disabled}
            title={o.title}
            onClick={() => !o.disabled && onChange(o.value)}
            className={cn(
              "px-2.5 py-1.5 text-xs font-medium transition",
              o.disabled
                ? "cursor-not-allowed text-faint"
                : value === o.value
                  ? "bg-surface-2 text-fg"
                  : "text-muted hover:text-fg",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

interface Scaled extends OverviewPoint {
  px: number;
  py: number;
}

// Exported so the scoped map dashboard (/maps/:id) can reuse the exact same
// scatter — points, cluster hulls, legend with glyphs, hover, and click-to-open.
export function Scatter({
  points,
  clusters,
  colorBy,
  sizeBy,
  showHulls,
  sims,
  labFilter,
  tagFilter,
  activeCluster,
  setActiveCluster,
  barHover,
}: {
  points: OverviewPoint[];
  clusters: Cluster[];
  colorBy: ColorMode;
  sizeBy: SizeMode;
  showHulls: boolean;
  sims: Record<string, number> | null;
  labFilter: string | null;
  tagFilter: string | null;
  activeCluster: number | null;
  setActiveCluster: (c: number | null) => void;
  barHover: BarHover;
}) {
  const { openPaper } = usePaperModal();
  const { categorical: cat, other, year: yearRamp, relevance: relRamp } = usePalette();
  const [hover, setHover] = useState<OverviewPoint | null>(null);


  // Rank-fraction of each paper's similarity (0..1), so the relevance ramp has
  // visible contrast even when raw cosine values sit in a narrow band.
  const relRank = useMemo(() => {
    if (!sims) return null;
    const entries = Object.entries(sims).sort((a, b) => a[1] - b[1]);
    const rank: Record<string, number> = {};
    const n = Math.max(1, entries.length - 1);
    entries.forEach(([id], i) => (rank[id] = i / n));
    return rank;
  }, [sims]);

  const { colorOf, legend } = useMemo(() => {
    if (colorBy === "relevance" && relRank) {
      return {
        colorOf: (p: OverviewPoint) => {
          const f = relRank[p.paper_id];
          return f == null ? other : relRamp[Math.round(f * (relRamp.length - 1))];
        },
        legend: [
          { key: "lo", color: relRamp[0], label: "less relevant", sub: undefined, title: undefined },
          { key: "hi", color: relRamp[relRamp.length - 1], label: "more relevant", sub: undefined, title: undefined },
        ],
      };
    }
    if (colorBy === "cluster") {
      const byId = new Map(clusters.map((c) => [c.id, c]));
      return {
        colorOf: (p: OverviewPoint) => cat[p.cluster % cat.length],
        legend: clusters.map((c) => ({
          key: String(c.id),
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
    const counts = new Map<string, number>();
    for (const p of points) if (p.venue) counts.set(p.venue, (counts.get(p.venue) ?? 0) + 1);
    // Bounded by the palette rather than a magic number: every named venue gets its
    // own hue, and the tail folds into "Other". (Was a hard-coded 7 against an
    // 8-colour scale.)
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, cat.length).map(([v]) => v);
    const color = new Map(top.map((v, i) => [v, cat[i]]));
    return {
      colorOf: (p: OverviewPoint) => (p.venue && color.has(p.venue) ? color.get(p.venue)! : other),
      legend: [
        ...top.map((v) => ({ key: v, color: color.get(v)!, label: v, sub: undefined, title: undefined })),
        { key: "__other", color: other, label: "Other", sub: undefined, title: undefined },
      ],
    };
  }, [colorBy, relRank, clusters, points, cat, yearRamp, relRamp, other]);

  const inRelevance = colorBy === "relevance" && relRank !== null;
  const maxEng = Math.max(1, ...points.map((p) => p.reactions + p.comments));
  // In relevance mode, size *and* alpha fall off with relevance so the
  // most-relevant papers pop; otherwise size follows the size control.
  const radiusOf = (p: OverviewPoint) => {
    if (inRelevance) return 2.5 + 6 * (relRank![p.paper_id] ?? 0);
    return sizeBy === "engagement" ? 3.5 + 6 * Math.sqrt((p.reactions + p.comments) / maxEng) : 5;
  };
  const alphaOf = (p: OverviewPoint) => {
    if (dimmed(p)) return 0.1;
    if (inRelevance) return 0.15 + 0.8 * (relRank![p.paper_id] ?? 0);
    return 0.92;
  };
  // Theme is the only categorical encoding, and six hues is at the limit of what's
  // distinguishable — under deuteranopia our cyan and magenta converge. So in theme
  // mode each cluster also gets its own glyph. The other modes are sequential (year,
  // relevance) or top-N (venue), where a shape would imply a grouping that isn't
  // there, so they stay circles.
  const markOf = (p: OverviewPoint) => (colorBy === "cluster" ? markFor(p.cluster) : "circle");

  const scaled: Scaled[] = useMemo(() => {
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
    const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
    const sx = (x: number) => (x1 === x0 ? W / 2 : PAD + ((x - x0) / (x1 - x0)) * (W - 2 * PAD));
    const sy = (y: number) => (y1 === y0 ? H / 2 : PAD + ((y1 - y) / (y1 - y0)) * (H - 2 * PAD));
    return points.map((p) => ({ ...p, px: sx(p.x), py: sy(p.y) }));
  }, [points]);

  // Faint convex-hull outline per theme, always drawn so themes stay legible
  // under any color mode.
  const hulls = useMemo(() => {
    const byCluster = new Map<number, Scaled[]>();
    for (const p of scaled) (byCluster.get(p.cluster) ?? byCluster.set(p.cluster, []).get(p.cluster)!).push(p);
    return [...byCluster.entries()]
      .map(([cid, pts]) => ({ cid, hull: convexHull(pts.map((p) => ({ x: p.px, y: p.py }))) }))
      .filter((h) => h.hull.length >= 3);
  }, [scaled]);

  const dimmed = (p: OverviewPoint) =>
    (activeCluster !== null && p.cluster !== activeCluster) ||
    (labFilter !== null && p.lab !== labFilter) ||
    (tagFilter !== null && !p.tags.includes(tagFilter)) ||
    (barHover !== null && String(barHoverValue(p, barHover)) !== barHover.value);

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
            {/* the legend carries the glyph too, or the shape encoding is unreadable */}
            <svg viewBox="0 0 12 12" width={11} height={11} className="shrink-0" aria-hidden>
              <path
                d={markPath(
                  colorBy === "cluster" ? markFor(Number(l.key)) : "circle",
                  6,
                  6,
                  4.4,
                )}
                fill={l.color}
              />
            </svg>
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
          {showHulls &&
            hulls.map(({ cid, hull }) => (
              <polygon
                key={cid}
                points={hull.map((pt) => `${pt.x},${pt.y}`).join(" ")}
                fill={cat[cid % cat.length]}
                fillOpacity={0.05}
                stroke={cat[cid % cat.length]}
                strokeOpacity={0.18}
                strokeWidth={1}
              />
            ))}
          {scaled.map((p) => (
            <path
              key={p.paper_id}
              d={markPath(
                markOf(p),
                p.px,
                p.py,
                hover?.paper_id === p.paper_id ? radiusOf(p) + 2 : radiusOf(p),
              )}
              fill={colorOf(p)}
              fillOpacity={alphaOf(p)}
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

function barHoverValue(p: OverviewPoint, bh: NonNullable<BarHover>): string | number | null {
  if (bh.kind === "year") {
    if (bh.value.startsWith("≤")) {
      const cutoff = Number(bh.value.slice(1));
      return p.year != null && p.year <= cutoff ? bh.value : null;
    }
    return p.year;
  }
  if (bh.kind === "venue") return p.venue;
  return p.lab;
}

function LabPapers({
  lab,
  papers,
  onClear,
}: {
  lab: string;
  papers: OverviewPoint[];
  onClear: () => void;
}) {
  const { openPaper } = usePaperModal();
  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm">
          <span className="font-semibold text-fg">{lab}</span>{" "}
          <span className="text-muted">— {papers.length} paper{papers.length === 1 ? "" : "s"} (last author)</span>
        </div>
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear lab filter"
          className="grid h-7 w-7 place-items-center rounded-control text-muted hover:bg-surface-2 hover:text-fg"
        >
          <X size={14} />
        </button>
      </div>
      <ul className="flex flex-col gap-0.5">
        {papers.map((p) => (
          <li key={p.paper_id}>
            <button
              type="button"
              onClick={() => openPaper(p.paper_id)}
              className="w-full rounded-control px-2 py-1.5 text-left text-sm transition hover:bg-surface-2"
            >
              <span className="text-fg">{p.title ?? "Untitled"}</span>
              {(p.venue || p.year) && (
                <span className="ml-2 font-mono text-xs text-faint">
                  {[p.venue, p.year].filter(Boolean).join(" · ")}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
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

/** Monotone-chain convex hull over 2-D points. */
function convexHull(pts: { x: number; y: number }[]): { x: number; y: number }[] {
  if (pts.length < 3) return pts;
  const p = [...pts].sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (o: { x: number; y: number }, a: { x: number; y: number }, b: { x: number; y: number }) =>
    (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: { x: number; y: number }[] = [];
  for (const pt of p) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], pt) <= 0) lower.pop();
    lower.push(pt);
  }
  const upper: { x: number; y: number }[] = [];
  for (let i = p.length - 1; i >= 0; i--) {
    const pt = p[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], pt) <= 0) upper.pop();
    upper.push(pt);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

function StatCard({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <span className="text-eyebrow font-bold uppercase tracking-eyebrow text-muted">{title}</span>
        {hint && <span className="text-[11px] font-normal normal-case text-faint">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmtMonth(ym: string): string {
  const [y, m] = ym.split("-");
  return `${MONTHS[Number(m) - 1] ?? m} ${y}`;
}

/** Keep the last 4 publication years; fold the (heavily skewed) older tail into
 *  one "≤YYYY" bar so it doesn't drown out the recent years. */
function groupYears(byYear: { year: number; count: number }[]): { label: string; value: number }[] {
  const sorted = [...byYear].sort((a, b) => a.year - b.year);
  if (sorted.length <= 5) return sorted.map((d) => ({ label: String(d.year), value: d.count }));
  const cutoff = sorted[sorted.length - 1].year - 3; // keep last 4 years individually
  const older = sorted.filter((d) => d.year < cutoff).reduce((s, d) => s + d.count, 0);
  const bars = sorted.filter((d) => d.year >= cutoff).map((d) => ({ label: String(d.year), value: d.count }));
  return older > 0 ? [{ label: `≤${cutoff - 1}`, value: older }, ...bars] : bars;
}

function SectionHeader({ children }: { children: ReactNode }) {
  return <h2 className="-mb-2 text-base font-semibold tracking-tight text-fg">{children}</h2>;
}

function deriveInsights(data: OverviewData): string[] {
  const out: string[] = [];
  const ot = data.stats.over_time;
  if (ot.length) {
    const b = ot.reduce((a, c) => (c.count > a.count ? c : a));
    out.push(`Busiest month: ${fmtMonth(b.month)} (${b.count})`);
  }
  const topTag = data.stats.by_tag[0];
  if (topTag) out.push(`Most common tag: ${topTag.tag} (${topTag.count})`);
  if (data.clusters.length) {
    const big = [...data.clusters].sort((a, b) => b.size - a.size)[0];
    out.push(`Largest theme: ${big.label} (${big.size})`);
  }
  return out;
}

function Insights({ data }: { data: OverviewData }) {
  const items = deriveInsights(data);
  if (!items.length) return null;
  return (
    <div className="-mt-3 flex flex-wrap gap-2">
      {items.map((t) => (
        <span
          key={t}
          className="rounded-chip border border-border bg-surface-2 px-2.5 py-1 text-xs text-muted"
        >
          {t}
        </span>
      ))}
    </div>
  );
}

function ThemeBars({
  clusters,
  cat,
  active,
  onToggle,
}: {
  clusters: Cluster[];
  cat: string[];
  active: number | null;
  onToggle: (id: number) => void;
}) {
  if (clusters.length === 0) return <p className="text-xs text-faint">No themes.</p>;
  const max = Math.max(1, ...clusters.map((c) => c.size));
  return (
    <div className="flex flex-col gap-1.5">
      {[...clusters]
        .sort((a, b) => b.size - a.size)
        .map((c) => (
          <button
            key={c.id}
            type="button"
            title={c.description}
            onClick={() => onToggle(c.id)}
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded px-1 text-left text-xs transition hover:bg-surface-2",
              active === c.id && "bg-surface-2",
            )}
          >
            <svg viewBox="0 0 12 12" width={11} height={11} className="shrink-0" aria-hidden>
              <path d={markPath(markFor(c.id), 6, 6, 4.4)} fill={cat[c.id % cat.length]} />
            </svg>
            <span className="w-32 shrink-0 truncate text-fg" title={c.label}>
              {c.label}
            </span>
            <div className="h-3 flex-1 overflow-hidden rounded bg-surface-2">
              <div
                className="h-full rounded"
                style={{ width: `${(c.size / max) * 100}%`, background: cat[c.id % cat.length] }}
              />
            </div>
            <span className="w-6 shrink-0 text-right font-mono tabular-nums text-faint">{c.size}</span>
          </button>
        ))}
    </div>
  );
}

function KpiStrip({ data }: { data: OverviewData }) {
  const ot = data.stats.over_time;
  const busiest = ot.length ? ot.reduce((a, b) => (b.count > a.count ? b : a)) : null;
  const range = ot.length ? `${fmtMonth(ot[0].month)} – ${fmtMonth(ot[ot.length - 1].month)}` : "—";
  const topVenue = data.stats.by_venue[0];
  const tiles: { label: string; value: string; sub?: string }[] = [
    { label: "Papers", value: String(data.total) },
    { label: "Embedded", value: `${data.embedded}` },
    { label: "Themes", value: String(data.clusters.length) },
    { label: "Shared", value: range },
    { label: "Busiest month", value: busiest ? fmtMonth(busiest.month) : "—", sub: busiest ? `${busiest.count}` : undefined },
    { label: "Top venue", value: topVenue?.venue ?? "—", sub: topVenue ? `${topVenue.count}` : undefined },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-card border border-border bg-surface p-3">
          <div className="text-eyebrow uppercase tracking-eyebrow text-faint">{t.label}</div>
          <div className="mt-1 truncate text-lg font-semibold text-fg" title={t.value}>
            {t.value}
            {t.sub && <span className="ml-1 text-xs font-normal text-muted">· {t.sub}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

/** A minimal bar chart in inline SVG (vertical) or CSS rows (horizontal), with
 *  optional hover (cross-highlight) and click (drill-down). */
function Bars({
  data,
  horizontal = false,
  onHover,
  onClick,
  activeLabel,
}: {
  data: { label: string; value: number }[];
  horizontal?: boolean;
  onHover?: (label: string | null) => void;
  onClick?: (label: string) => void;
  activeLabel?: string | null;
}) {
  if (data.length === 0) return <p className="text-xs text-faint">No data.</p>;
  const max = Math.max(...data.map((d) => d.value));

  if (horizontal) {
    return (
      <div className="flex flex-col gap-1.5" onMouseLeave={() => onHover?.(null)}>
        {data.map((d) => (
          <button
            key={d.label}
            type="button"
            onMouseEnter={() => onHover?.(d.label)}
            onClick={() => onClick?.(d.label)}
            className={cn(
              "flex items-center gap-2 rounded px-1 text-left text-xs transition",
              onClick ? "cursor-pointer hover:bg-surface-2" : "cursor-default",
              activeLabel === d.label && "bg-surface-2",
            )}
          >
            <span className="w-28 shrink-0 truncate text-muted" title={d.label}>
              {d.label}
            </span>
            <div className="h-3 flex-1 overflow-hidden rounded bg-surface-2">
              <div className="h-full rounded bg-accent" style={{ width: `${(d.value / max) * 100}%` }} />
            </div>
            <span className="w-6 shrink-0 text-right font-mono tabular-nums text-faint">{d.value}</span>
            {onClick && <ChevronRight size={12} className="shrink-0 text-faint" />}
          </button>
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
              onMouseEnter={() => onHover?.(d.label)}
              onMouseLeave={() => onHover?.(null)}
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
