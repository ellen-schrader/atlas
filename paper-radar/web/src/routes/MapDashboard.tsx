import { type ReactNode, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Loader2, MessageSquare, Search, Smile, X } from "lucide-react";

import { usePaperModal } from "@/components/PaperModal";
import { fetchMapOverview, fetchMapPapers, isTransientApiError } from "@/lib/api";
import { usePalette } from "@/lib/palette";
import type { MapPaper } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";
import { Scatter } from "@/routes/Map";

type Sort = "importance" | "recent" | "discussed";
const paperLab = (p: MapPaper) => (p.authors.length ? p.authors[p.authors.length - 1] : null);

/**
 * A topic map's dashboard: the scoped t-SNE + sub-themes (M2), and the ranked,
 * searchable, filterable member papers with the caller's read-state, plus the
 * labs driving the topic (M3). The AI summary lands in M4.
 */
export default function MapDashboard() {
  const { mapId } = useParams<{ mapId: string }>();
  const { team } = useAppContext();
  const [activeCluster, setActiveCluster] = useState<number | null>(null);
  const [sort, setSort] = useState<Sort>("importance");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [labFilter, setLabFilter] = useState<string | null>(null);

  const overview = useQuery({
    queryKey: ["map-overview", mapId],
    queryFn: () => fetchMapOverview(mapId!),
    enabled: !!mapId,
    retry: (n, e) => isTransientApiError(e) && n < 5,
  });
  const papers = useQuery({
    queryKey: ["map-papers", mapId, sort],
    queryFn: () => fetchMapPapers(mapId!, sort),
    enabled: !!mapId,
    retry: (n, e) => isTransientApiError(e) && n < 5,
  });

  const data = overview.data;
  const shown = useMemo(() => {
    const all = papers.data?.papers ?? [];
    const q = search.trim().toLowerCase();
    return all.filter(
      (p) =>
        (!unreadOnly || p.read_status !== "read") &&
        (!labFilter || paperLab(p) === labFilter) &&
        (!q || (p.title ?? "").toLowerCase().includes(q)),
    );
  }, [papers.data, unreadOnly, labFilter, search]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 p-8">
      <Link to="/maps" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft size={14} /> Maps
      </Link>

      {overview.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted">
          <Loader2 size={16} className="animate-spin" /> Mapping this topic…
        </div>
      )}
      {overview.error && <p className="text-sm text-danger">{(overview.error as Error).message}</p>}

      {data && (
        <>
          <header>
            <p className="text-xs font-semibold uppercase tracking-wide text-accent">Topic map</p>
            <h1 className="font-serif text-display font-semibold tracking-tight text-fg">
              {data.name}
            </h1>
            <p className="mt-1 text-sm text-muted">
              papers near <span className="font-serif italic text-fg">{data.seed}</span>
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Chip>
                {data.total} paper{data.total === 1 ? "" : "s"}
              </Chip>
              {data.new_this_week > 0 && <Chip accent>+{data.new_this_week} this week</Chip>}
              <Chip>{data.visibility === "lab" ? `Shared with ${team.name}` : "Only you"}</Chip>
            </div>
          </header>

          {data.points.length >= 2 ? (
            <section className="rounded-card border border-border bg-surface p-5">
              <h2 className="mb-1 font-serif text-lg font-semibold tracking-tight">The map</h2>
              <p className="mb-3 text-xs text-faint">
                {data.embedded} papers · {data.clusters.length} sub-theme
                {data.clusters.length === 1 ? "" : "s"} · t-SNE of embeddings
              </p>
              <Scatter
                points={data.points}
                clusters={data.clusters}
                colorBy="cluster"
                sizeBy="engagement"
                showHulls
                sims={null}
                labFilter={null}
                tagFilter={null}
                activeCluster={activeCluster}
                setActiveCluster={setActiveCluster}
                barHover={null}
              />
            </section>
          ) : (
            <div className="rounded-card border border-dashed border-border p-8 text-center text-sm text-faint">
              {data.total === 0
                ? "No papers match this topic yet. As the lab posts more, they’ll appear here."
                : "Only a paper or two here so far — too few to map. Broaden the seed, or add more papers to the lab."}
            </div>
          )}

          {data.total > 0 && (
            <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
              {/* important papers */}
              <section className="rounded-card border border-border bg-surface p-5">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="font-serif text-lg font-semibold tracking-tight">
                    Important papers
                  </h2>
                  <Segmented
                    value={sort}
                    onChange={setSort}
                    options={[
                      { value: "importance", label: "Important" },
                      { value: "recent", label: "Recent" },
                      { value: "discussed", label: "Discussed" },
                    ]}
                  />
                </div>

                <div className="mb-2.5 flex items-center gap-2 rounded-control border border-border bg-surface-2 px-2.5 py-1.5">
                  <Search size={14} className="text-faint" />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search within this map…"
                    className="flex-1 bg-transparent text-sm text-fg outline-none"
                  />
                </div>

                <div className="mb-3 flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    aria-pressed={unreadOnly}
                    onClick={() => setUnreadOnly((v) => !v)}
                    className={cn(
                      "rounded-chip border px-2.5 py-1 text-xs font-medium transition",
                      unreadOnly
                        ? "border-transparent bg-accent text-accent-fg"
                        : "border-border text-muted hover:text-fg",
                    )}
                  >
                    Unread
                  </button>
                  {labFilter && (
                    <span className="inline-flex items-center gap-1 rounded-chip border border-border bg-surface-2 px-2 py-1 text-xs">
                      Lab: {labFilter}
                      <button type="button" aria-label="Clear lab filter" onClick={() => setLabFilter(null)}>
                        <X size={11} className="text-muted hover:text-danger" />
                      </button>
                    </span>
                  )}
                </div>

                {papers.isLoading ? (
                  <p className="py-6 text-center text-sm text-faint">Loading papers…</p>
                ) : shown.length ? (
                  <ul className="flex flex-col">
                    {shown.map((p) => (
                      <PaperRow key={p.paper_id} p={p} />
                    ))}
                  </ul>
                ) : (
                  <p className="py-6 text-center text-sm text-faint">
                    {unreadOnly ? "Nothing unread here — you’re caught up." : "No papers match."}
                  </p>
                )}
              </section>

              {/* rail: labs + sub-themes */}
              <aside className="flex flex-col gap-4">
                <RankPanel title="Labs driving this topic">
                  <RankBars
                    items={(papers.data?.labs ?? []).map((l) => ({ label: l.lab, count: l.count }))}
                    activeLabel={labFilter}
                    onPick={(label) => setLabFilter((cur) => (cur === label ? null : label))}
                    empty="No author information yet."
                  />
                </RankPanel>
                <RankPanel title="Sub-themes">
                  <RankBars
                    items={data.clusters.map((c) => ({ label: c.label, count: c.size, tone: c.id }))}
                    activeLabel={null}
                    onPick={(_, tone) =>
                      setActiveCluster((cur) => (cur === (tone ?? null) ? null : (tone ?? null)))
                    }
                    empty="Too few papers to cluster."
                  />
                </RankPanel>
              </aside>
            </div>
          )}

          <p className="text-xs text-faint">
            Coming next (M4): an AI summary of recent developments in this map, grounded in and
            citing the lab’s papers.
          </p>
        </>
      )}
    </div>
  );
}

function PaperRow({ p }: { p: MapPaper }) {
  const { openPaper } = usePaperModal();
  const meta = [p.authors.slice(0, 3).join(", "), p.venue, p.year].filter(Boolean).join(" · ");
  const rel = p.similarity == null ? null : Math.round(Math.max(0, p.similarity) * 100);
  const dot =
    p.read_status === "read"
      ? "bg-faint border-faint"
      : p.read_status === "reading"
        ? "bg-accent border-accent"
        : "bg-transparent border-accent"; // to_read / null = unread
  return (
    <li className="flex gap-3 border-t border-border py-2.5 first:border-t-0">
      <span
        className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full border", dot)}
        title={p.read_status ?? "unread"}
      />
      <button
        type="button"
        onClick={() => openPaper(p.paper_id)}
        className="min-w-0 flex-1 text-left"
      >
        <div className="truncate text-sm font-semibold text-fg">{p.title ?? "(untitled)"}</div>
        <div className="truncate text-xs text-muted">
          {meta}
          {rel != null && <span className="text-accent"> · {rel}% match</span>}
        </div>
      </button>
      <div className="flex shrink-0 items-center gap-2 pt-0.5 text-xs text-faint">
        <span className="inline-flex items-center gap-0.5">
          <MessageSquare size={12} /> {p.comments}
        </span>
        <span className="inline-flex items-center gap-0.5">
          <Smile size={12} /> {p.reactions}
        </span>
      </div>
    </li>
  );
}

function RankPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-card border border-border bg-surface p-4">
      <h3 className="mb-2 font-serif text-base font-semibold tracking-tight">{title}</h3>
      {children}
    </section>
  );
}

function RankBars({
  items,
  activeLabel,
  onPick,
  empty,
}: {
  items: { label: string; count: number; tone?: number }[];
  activeLabel: string | null;
  onPick: (label: string, tone?: number) => void;
  empty: string;
}) {
  const { categorical } = usePalette();
  if (!items.length) return <p className="text-xs text-faint">{empty}</p>;
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((it) => (
        <li key={it.label}>
          <button
            type="button"
            onClick={() => onPick(it.label, it.tone)}
            className={cn(
              "w-full text-left",
              activeLabel === it.label && "font-semibold text-accent",
            )}
          >
            <div className="flex items-center justify-between text-sm">
              <span className="truncate pr-2">{it.label}</span>
              <span className="tabular-nums text-faint">{it.count}</span>
            </div>
            <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-surface-3">
              <span
                className="block h-full rounded-full"
                style={{
                  width: `${(it.count / max) * 100}%`,
                  background:
                    it.tone == null ? "var(--accent)" : categorical[it.tone % categorical.length],
                }}
              />
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div className="flex overflow-hidden rounded-control border border-border">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "px-2.5 py-1 text-xs font-medium transition",
            value === o.value ? "bg-surface-2 text-fg" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Chip({ children, accent }: { children: ReactNode; accent?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-chip border px-2 py-0.5",
        accent
          ? "border-accent/40 bg-accent-weak font-semibold text-accent"
          : "border-border bg-surface text-muted",
      )}
    >
      {children}
    </span>
  );
}
