import { type ReactNode, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Ban,
  Check,
  Loader2,
  MessageSquare,
  Pin,
  RefreshCw,
  Search,
  Settings2,
  Smile,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { usePaperModal } from "@/components/PaperModal";
import {
  deleteMap,
  fetchMapOverview,
  fetchMapPapers,
  fetchMapSummary,
  generateMapSummary,
  isTransientApiError,
  type MapPatch,
  updateMap,
} from "@/lib/api";
import { usePalette } from "@/lib/palette";
import { supabase } from "@/lib/supabase";
import type { MapOverviewData, MapPaper, MapSummary } from "@/lib/types";
import { cn, formatRelative } from "@/lib/utils";
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
  const { team, userId } = useAppContext();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
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
  const qc = useQueryClient();
  const summary = useQuery({
    queryKey: ["map-summary", mapId],
    queryFn: () => fetchMapSummary(mapId!),
    enabled: !!mapId,
  });
  const regen = useMutation({
    mutationFn: () => generateMapSummary(mapId!),
    onSuccess: (s) => qc.setQueryData(["map-summary", mapId], s),
  });
  // One curation action → refresh the scatter + list (the summary stays cached
  // until the user regenerates it).
  const curate = useMutation({
    mutationFn: (patch: MapPatch) => updateMap(mapId!, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["map-overview", mapId] });
      qc.invalidateQueries({ queryKey: ["map-papers", mapId] });
    },
  });
  // Quick read toggle from a row: mark read, or clear back to unread. (Clearing
  // also drops a reading-list "to_read" on that paper — an accepted simplification.)
  const setRead = useMutation({
    mutationFn: async ({ paperId, read }: { paperId: string; read: boolean }) => {
      const base = supabase.from("paper_status");
      if (read) {
        await base.upsert(
          { user_id: userId, team_id: team.id, paper_id: paperId, status: "read" },
          { onConflict: "user_id,team_id,paper_id" },
        );
      } else {
        await base.delete().eq("user_id", userId).eq("team_id", team.id).eq("paper_id", paperId);
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["map-papers", mapId] }),
  });
  // A cited paper can drop out of the map after curation; resolve to undefined so
  // the summary can hide a now-stale source chip rather than showing "source".
  const titleOf = (id: string): string | undefined =>
    papers.data?.papers.find((p) => p.paper_id === id)?.title ?? undefined;

  const data = overview.data;
  const canEdit = !!data && data.created_by === userId;
  const pinnedIds = useMemo(
    () => new Set((papers.data?.papers ?? []).filter((p) => p.pinned).map((p) => p.paper_id)),
    [papers.data],
  );
  // The overview points carry each paper's sub-theme, so a sub-theme click can
  // filter the list too (no extra fetch) — the cross-filter symmetry.
  const clusterByPid = useMemo(
    () => new Map((data?.points ?? []).map((p) => [p.paper_id, p.cluster])),
    [data],
  );
  const shown = useMemo(() => {
    const all = papers.data?.papers ?? [];
    const q = search.trim().toLowerCase();
    const filtered = all.filter(
      (p) =>
        (!unreadOnly || p.read_status !== "read") &&
        (!labFilter || paperLab(p) === labFilter) &&
        (activeCluster == null || clusterByPid.get(p.paper_id) === activeCluster) &&
        (!q || (p.title ?? "").toLowerCase().includes(q)),
    );
    // A pin is a must-have, so float pinned papers to the top of whatever sort.
    return [...filtered].sort((a, b) => Number(b.pinned) - Number(a.pinned));
  }, [papers.data, unreadOnly, labFilter, activeCluster, clusterByPid, search]);

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
            <div className="flex items-start gap-2">
              <h1 className="font-serif text-display font-semibold tracking-tight text-fg">
                {data.name}
              </h1>
              {canEdit && (
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  title="Edit map"
                  className="mt-2 shrink-0 rounded-control border border-border px-2 py-1 text-xs font-medium text-muted transition hover:border-accent hover:text-accent"
                >
                  <span className="inline-flex items-center gap-1">
                    <Settings2 size={13} /> Edit
                  </span>
                </button>
              )}
            </div>
            <p className="mt-1 text-sm text-muted">
              papers near <span className="font-serif italic text-fg">{data.seed}</span>
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Chip>
                {data.total} paper{data.total === 1 ? "" : "s"}
              </Chip>
              {/* Suppress when it equals the total — an all-new map isn't "news". */}
              {data.new_this_week > 0 && data.new_this_week < data.total && (
                <Chip accent>+{data.new_this_week} this week</Chip>
              )}
              <Chip>{data.visibility === "lab" ? `Shared with ${team.name}` : "Only you"}</Chip>
            </div>
            {data.below_threshold > 0 && (
              <p className="mt-2 text-xs text-faint">
                {data.below_threshold} more paper{data.below_threshold === 1 ? " is" : "s are"} loosely
                related to this topic.
                {canEdit && (
                  <button
                    type="button"
                    disabled={curate.isPending}
                    onClick={() =>
                      curate.mutate({ min_similarity: Math.max(-1, data.min_similarity - 0.1) })
                    }
                    className="ml-1.5 font-medium text-accent hover:underline disabled:opacity-50"
                  >
                    Broaden the match →
                  </button>
                )}
              </p>
            )}
          </header>

          {editing && data && (
            <MapEditPanel
              data={data}
              onClose={() => setEditing(false)}
              onSave={(patch) => {
                curate.mutate(patch);
                setEditing(false);
              }}
              onDelete={() => {
                if (window.confirm(`Delete the map “${data.name}”?`)) {
                  deleteMap(data.map_id).then(() => navigate("/maps"));
                }
              }}
              saving={curate.isPending}
            />
          )}

          {data.total === 0 ? (
            <div className="rounded-card border border-dashed border-border p-8 text-center text-sm text-faint">
              No papers match this topic yet. As the lab posts more, they’ll appear here.
            </div>
          ) : (
            <>
              {/* Top band: the map (hero, left) beside a continuous rail — the
                  summary, sub-themes and labs — so the right column isn't starved. */}
              <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
                <div className="lg:order-1">
                  {data.points.length >= 2 ? (
                    <section className="h-full rounded-card border border-border bg-surface p-5">
                      <h2 className="mb-1 font-serif text-lg font-semibold tracking-tight">
                        The map
                      </h2>
                      <p className="mb-3 text-xs text-faint">
                        {data.embedded} papers · {data.clusters.length} sub-theme
                        {data.clusters.length === 1 ? "" : "s"} · hover a point to preview, click to
                        open
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
                        pinnedIds={pinnedIds}
                      />
                    </section>
                  ) : (
                    <div className="rounded-card border border-dashed border-border p-8 text-center text-sm text-faint">
                      Only a paper or two here so far — too few to map. Broaden the seed, or add more
                      papers to the lab.
                    </div>
                  )}
                </div>
                <aside className="flex flex-col gap-4 lg:order-2">
                  <WhatsNew
                    summary={summary.data}
                    loading={summary.isLoading}
                    generating={regen.isPending}
                    onGenerate={() => regen.mutate()}
                    titleOf={titleOf}
                  />
                  <RankPanel title="Sub-themes">
                    <RankBars
                      items={data.clusters.map((c) => ({ label: c.label, count: c.size, tone: c.id }))}
                      activeLabel={
                        activeCluster == null
                          ? null
                          : (data.clusters.find((c) => c.id === activeCluster)?.label ?? null)
                      }
                      onPick={(_, tone) =>
                        setActiveCluster((cur) => (cur === (tone ?? null) ? null : (tone ?? null)))
                      }
                      empty="Too few papers to cluster."
                    />
                  </RankPanel>
                  {(papers.data?.labs.length ?? 0) > 0 && (
                    <RankPanel title="Labs driving this topic">
                      <RankBars
                        items={(papers.data?.labs ?? []).map((l) => ({
                          label: l.lab,
                          count: l.count,
                        }))}
                        activeLabel={labFilter}
                        onPick={(label) => setLabFilter((cur) => (cur === label ? null : label))}
                        empty=""
                      />
                    </RankPanel>
                  )}
                </aside>
              </div>

              {/* Important papers — full width below the band: the reading queue. */}
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
                  {activeCluster != null && (
                    <span className="inline-flex items-center gap-1 rounded-chip border border-border bg-surface-2 px-2 py-1 text-xs">
                      {data.clusters.find((c) => c.id === activeCluster)?.label ?? "Sub-theme"}
                      <button
                        type="button"
                        aria-label="Clear sub-theme filter"
                        onClick={() => setActiveCluster(null)}
                      >
                        <X size={11} className="text-muted hover:text-danger" />
                      </button>
                    </span>
                  )}
                  {/* key for the read-state dot, so it isn't colour/shape alone */}
                  <span className="ml-auto flex items-center gap-2.5 self-center text-[0.7rem] text-faint">
                    <ReadKey cls="border-accent" label="unread" />
                    <ReadKey cls="bg-accent border-accent" label="reading" />
                    <ReadKey cls="bg-faint border-faint" label="read" />
                  </span>
                </div>

                {papers.isLoading ? (
                  <p className="py-6 text-center text-sm text-faint">Loading papers…</p>
                ) : shown.length ? (
                  <>
                    {/* A long topic has hundreds of members — cap the height and
                        scroll rather than letting the list run off the page. */}
                    <ul className="-mr-1 flex max-h-[22rem] flex-col overflow-y-auto pr-1">
                      {shown.map((p) => (
                        <PaperRow
                          key={p.paper_id}
                          p={p}
                          canEdit={canEdit}
                          busy={curate.isPending}
                          onCurate={(patch) => curate.mutate(patch)}
                          onToggleRead={(read) => setRead.mutate({ paperId: p.paper_id, read })}
                        />
                      ))}
                    </ul>
                    <p className="mt-2 text-xs text-faint">
                      {shown.length} paper{shown.length === 1 ? "" : "s"}
                      {shown.length > 6 ? " · scroll for more" : ""}
                    </p>
                  </>
                ) : (
                  <p className="py-6 text-center text-sm text-faint">
                    {unreadOnly ? "Nothing unread here — you’re caught up." : "No papers match."}
                  </p>
                )}
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}

const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

function MapEditPanel({
  data,
  onClose,
  onSave,
  onDelete,
  saving,
}: {
  data: MapOverviewData;
  onClose: () => void;
  onSave: (patch: MapPatch) => void;
  onDelete: () => void;
  saving: boolean;
}) {
  const [name, setName] = useState(data.name);
  const [seed, setSeed] = useState(data.seed);
  const [visibility, setVisibility] = useState<"lab" | "private">(
    data.visibility === "private" ? "private" : "lab",
  );
  const [minSim, setMinSim] = useState(data.min_similarity);
  const save = () => {
    const patch: MapPatch = {};
    if (name.trim() && name.trim() !== data.name) patch.name = name.trim();
    if (seed.trim() && seed.trim() !== data.seed) patch.seed = seed.trim();
    if (visibility !== data.visibility) patch.visibility = visibility;
    if (minSim !== data.min_similarity) patch.min_similarity = minSim;
    onSave(patch);
  };
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-card border border-border bg-surface p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-serif text-lg font-semibold tracking-tight">Edit map</h2>
          <button type="button" onClick={onClose} aria-label="Close">
            <X size={16} className="text-muted hover:text-fg" />
          </button>
        </div>

        <label className="block text-xs font-medium text-muted">Name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mb-3 mt-1 w-full rounded-control border border-border bg-surface-2 px-3 py-2 text-sm text-fg outline-none focus:border-accent"
        />
        <label className="block text-xs font-medium text-muted">
          What it’s about (re-seeds membership)
        </label>
        <input
          value={seed}
          onChange={(e) => setSeed(e.target.value)}
          className="mb-3 mt-1 w-full rounded-control border border-border bg-surface-2 px-3 py-2 text-sm text-fg outline-none focus:border-accent"
        />
        <label className="block text-xs font-medium text-muted">
          Match threshold — a paper joins at ≥ {Math.round(minSim * 100)}% similarity
        </label>
        <input
          type="range"
          min={-1}
          max={1}
          step={0.05}
          value={minSim}
          onChange={(e) => setMinSim(Number(e.target.value))}
          className="mb-3 mt-1 w-full accent-accent"
        />
        <div className="mb-4 flex gap-2">
          {(["lab", "private"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setVisibility(v)}
              className={cn(
                "rounded-control border px-3 py-1.5 text-xs font-medium transition",
                visibility === v
                  ? "border-accent bg-accent-weak text-accent"
                  : "border-border text-muted hover:text-fg",
              )}
            >
              {v === "lab" ? "Shared with lab" : "Only me"}
            </button>
          ))}
        </div>

        {data.excluded_count > 0 && (
          <div className="mb-4 flex items-center justify-between rounded-control border border-border bg-surface-2 px-3 py-2 text-xs">
            <span className="text-muted">
              {data.excluded_count} paper{data.excluded_count === 1 ? "" : "s"} dismissed
            </span>
            <button
              type="button"
              onClick={() => onSave({ clear_excluded: true })}
              className="font-medium text-accent hover:underline"
            >
              Restore all
            </button>
          </div>
        )}

        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={onDelete}
            className="inline-flex items-center gap-1 text-xs font-medium text-danger hover:underline"
          >
            <Trash2 size={13} /> Delete map
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-3 py-1.5 text-sm text-muted hover:text-fg"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-accent-fg transition hover:brightness-110 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReadKey({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className={cn("h-2 w-2 rounded-full border", cls)} />
      {label}
    </span>
  );
}

function WhatsNew({
  summary,
  loading,
  generating,
  onGenerate,
  titleOf,
}: {
  summary: MapSummary | undefined;
  loading: boolean;
  generating: boolean;
  onGenerate: () => void;
  titleOf: (id: string) => string | undefined;
}) {
  const { openPaper } = usePaperModal();
  const has = Boolean(summary?.text);
  // Only cited papers still in the map (curation/threshold can drop one out).
  const sources = (summary?.cited_ids ?? [])
    .map((id) => ({ id, title: titleOf(id) }))
    .filter((s): s is { id: string; title: string } => Boolean(s.title));
  return (
    <section className="rounded-card border border-border bg-surface p-5">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 font-serif text-lg font-semibold tracking-tight">
          <Sparkles size={16} className="text-accent" /> What’s new
        </h2>
        {has && (
          <button
            type="button"
            onClick={onGenerate}
            disabled={generating}
            className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline disabled:opacity-50"
          >
            {generating ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Regenerate
          </button>
        )}
      </div>

      {loading ? (
        <p className="text-sm text-faint">Loading…</p>
      ) : generating && !has ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 size={14} className="animate-spin" /> Reading the recent papers…
        </p>
      ) : has && summary ? (
        <>
          <p className="text-sm leading-relaxed text-fg">{summary.text}</p>
          {sources.length > 0 && (
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-faint">Sources:</span>
              {sources.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => openPaper(s.id)}
                  className="rounded-chip border border-border bg-surface-2 px-2 py-0.5 text-accent transition hover:border-accent"
                >
                  {truncate(s.title, 40)}
                </button>
              ))}
            </div>
          )}
          <p className="mt-2.5 text-xs text-faint">
            {summary.ai ? "Synthesized from" : "Based on"} {summary.n_papers} of the lab’s papers
            {summary.ai
              ? " · grounded in them, nothing invented"
              : " · add an Anthropic key for an AI synthesis"}
            {summary.generated_at ? ` · ${formatRelative(summary.generated_at)}` : ""}.
          </p>
        </>
      ) : (
        <div className="flex flex-col items-start gap-2.5">
          <p className="text-sm text-muted">
            Get a short, cited brief of what’s moved in this topic recently — built only from the
            lab’s own papers.
          </p>
          <button
            type="button"
            onClick={onGenerate}
            disabled={generating}
            className="inline-flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-accent-fg transition hover:brightness-110 disabled:opacity-50"
          >
            {generating ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Summarize what’s new
          </button>
        </div>
      )}
    </section>
  );
}

function PaperRow({
  p,
  canEdit,
  busy,
  onCurate,
  onToggleRead,
}: {
  p: MapPaper;
  canEdit: boolean;
  busy: boolean;
  onCurate: (patch: MapPatch) => void;
  onToggleRead: (read: boolean) => void;
}) {
  const { openPaper } = usePaperModal();
  const meta = [p.authors.slice(0, 3).join(", "), p.venue, p.year].filter(Boolean).join(" · ");
  // Hide a ~0% match: it reads as "irrelevant" and adds noise on every row.
  const rel = p.similarity == null ? null : Math.round(Math.max(0, p.similarity) * 100);
  const dot =
    p.read_status === "read"
      ? "bg-faint border-faint"
      : p.read_status === "reading"
        ? "bg-accent border-accent"
        : "bg-transparent border-accent"; // to_read / null = unread
  return (
    <li className="group flex gap-3 border-t border-border py-2.5 first:border-t-0">
      <span
        className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full border", dot)}
        title={p.read_status ?? "unread"}
      />
      <button
        type="button"
        onClick={() => openPaper(p.paper_id)}
        className="min-w-0 flex-1 text-left"
      >
        <div className="flex items-center gap-1.5">
          {p.pinned && (
            <Pin size={11} className="-rotate-45 shrink-0 text-accent" aria-label="pinned" />
          )}
          <span className="truncate text-sm font-semibold text-fg">{p.title ?? "(untitled)"}</span>
        </div>
        <div className="truncate text-xs text-muted">
          {meta}
          {rel != null && rel > 0 && <span className="text-accent"> · {rel}% match</span>}
        </div>
      </button>
      <div className="flex shrink-0 items-center gap-2 pt-0.5 text-xs text-faint">
        <button
          type="button"
          title={p.read_status === "read" ? "Mark unread" : "Mark read"}
          onClick={() => onToggleRead(p.read_status !== "read")}
          className={cn(
            "opacity-0 transition hover:text-accent group-hover:opacity-100",
            p.read_status === "read" && "text-accent opacity-100",
          )}
        >
          <Check size={13} />
        </button>
        {canEdit && (
          <span className="flex items-center gap-1.5 opacity-0 transition group-hover:opacity-100">
            <button
              type="button"
              disabled={busy}
              title={p.pinned ? "Unpin" : "Pin to this map"}
              onClick={() => onCurate(p.pinned ? { unpin: p.paper_id } : { pin: p.paper_id })}
              className={cn("hover:text-accent disabled:opacity-40", p.pinned && "text-accent")}
            >
              <Pin size={13} className="-rotate-45" />
            </button>
            <button
              type="button"
              disabled={busy}
              title="Not relevant — remove from this map"
              onClick={() => onCurate({ exclude: p.paper_id })}
              className="hover:text-danger disabled:opacity-40"
            >
              <Ban size={13} />
            </button>
          </span>
        )}
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
