import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  Lock,
  MoreHorizontal,
  Plus,
  Search,
  Users,
  X,
} from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { BookmarkButton } from "@/components/BookmarkButton";
import { SelectCheckbox } from "@/components/ExportBar";
import { Segmented } from "@/components/home/HomeSection";
import { PaperPicker, type PickedPaper } from "@/components/PaperPicker";
import { usePaperModal } from "@/components/PaperModal";
import { PreprintBadge } from "@/components/PreprintBadge";
import { AroundProject, type Facet, facetName } from "@/components/projects/AroundProject";
import { ChartLegend, ClosenessChart, type Dot } from "@/components/projects/ClosenessChart";
import { ProjectDialog, ShareDialog } from "@/components/projects/ProjectDialogs";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { useDismissable } from "@/hooks/useDismissable";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useMembers } from "@/hooks/useMembers";
import { useMyRole } from "@/hooks/useMyRole";
import {
  useCloseness,
  usePaperInfo,
  useProject,
  useProjectFollows,
  useProjectPapers,
  useRefreshProject,
} from "@/hooks/useProjects";
import { useReadingList } from "@/hooks/useReadingList";
import { useReadPapers } from "@/hooks/useReadPapers";
import { updateProject } from "@/lib/api";
import { downloadText, exportFilename, formatPapers, FORMAT_META } from "@/lib/paperExport";
import { isPreprintVenue } from "@/lib/preprint";
import { facetItems, hasFacet, type Range } from "@/lib/projectFacets";
import {
  type Closeness,
  LEVELS,
  type PaperInfo,
  type Project,
  type SuggestLevel,
  VISIBILITY,
  clearPapers,
  deleteProject,
  markViewed,
  projectPeople,
  setFollow,
  setPapers,
} from "@/lib/projects";
import { supabase } from "@/lib/supabase";
import { cn, formatAgo, formatAuthors, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

type Tab = "in" | "suggested";
type Sort = "close" | "added" | "year" | "title";

const SORTS: { value: Sort; label: string }[] = [
  { value: "close", label: "Closest first" },
  { value: "added", label: "Recently added" },
  { value: "year", label: "Newest published" },
  { value: "title", label: "Title" },
];

/** When the caller last opened the project, read once before this visit is
 *  recorded, so what arrived since is still marked new while they look. */
function useLastViewed(projectId: string | undefined, userId: string) {
  const { data } = useQuery({
    queryKey: ["project-last-viewed", projectId, userId],
    enabled: !!projectId,
    staleTime: Infinity,
    gcTime: 0,
    queryFn: async (): Promise<string | null> => {
      const { data, error } = await supabase
        .from("project_views")
        .select("last_viewed_at")
        .eq("project_id", projectId as string)
        .eq("user_id", userId);
      if (error) throw error;
      const seen = (data ?? [])[0]?.last_viewed_at ?? null;
      await markViewed(projectId as string);
      return seen;
    },
  });
  return data;
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const { team, userId } = useAppContext();
  const { data: project, isLoading, isError } = useProject(id);
  useDocumentTitle(project?.name ?? "Project");

  if (isLoading) return <div className="p-8 text-sm text-muted">Loading…</div>;
  if (isError)
    return (
      <p role="alert" className="p-8 text-sm text-danger">
        Couldn’t load this project. Check your connection and reload.
      </p>
    );
  if (!project)
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-3 p-8">
        <h1 className="text-display font-bold tracking-tight">Project not found</h1>
        <p className="text-sm text-muted">
          It may have been deleted, or it isn’t shared with you.{" "}
          <Link to="/projects" className="text-accent hover:underline">
            Back to projects
          </Link>
        </p>
      </div>
    );
  // Everything on the page (the library, members, the reading list) is the
  // project's lab's, so it only opens from that lab.
  if (project.team_id !== team.id)
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-3 p-8">
        <h1 className="text-display font-bold tracking-tight">{project.name}</h1>
        <p className="text-sm text-muted">
          This project belongs to another of your labs. Switch to that lab from your profile menu to
          open it.
        </p>
      </div>
    );
  return <ProjectView key={project.id} project={project} teamId={team.id} teamName={team.name} userId={userId} />;
}

function ProjectView({
  project,
  teamId,
  teamName,
  userId,
}: {
  project: Project;
  teamId: string;
  teamName: string;
  userId: string;
}) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, confirmDialog] = useConfirm();
  const refresh = useRefreshProject();
  const { openPaper } = usePaperModal();
  const owner = project.owner_id === userId;
  const { data: myRole } = useMyRole(teamId, userId);
  // A lab owner may delete a project whose owner has left (projects_delete_orphan).
  const canDelete = owner || (project.owner_id === null && myRole === "owner");

  const { data: closeness, isLoading: loadingCloseness } = useCloseness(project.id);
  const { data: members } = useProjectPapers(project.id);
  const { data: follows } = useProjectFollows(project.id);
  const { data: lab } = useMembers(teamId);
  const { data: reading } = useReadingList(userId, teamId);
  const { data: read } = useReadPapers(userId, teamId);
  const lastViewed = useLastViewed(project.id, userId);

  const rows = useMemo(() => closeness ?? [], [closeness]);
  const byId = useMemo(() => new Map(rows.map((r) => [r.paper_id, r])), [rows]);
  const memberRows = useMemo(() => members ?? [], [members]);
  const inIds = useMemo(
    () => memberRows.filter((m) => m.state === "in").map((m) => m.paper_id),
    [memberRows],
  );
  const dismissedIds = memberRows.filter((m) => m.state === "dismissed").map((m) => m.paper_id);
  const memberOf = useMemo(() => new Map(memberRows.map((m) => [m.paper_id, m])), [memberRows]);

  // --- view state ---
  const [tab, setTab] = useState<Tab>("in");
  const [sort, setSort] = useState<Sort>("close");
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<Facet | null>(null);
  const [hoverFacet, setHoverFacet] = useState<Facet | null>(null);
  /** "N not in it": the related papers with a tag or lab, beyond Suggested. */
  const [wide, setWide] = useState(false);
  const [range, setRange] = useState<Range>("all");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);

  // A selection only ever covers papers on screen: changing what is shown clears it.
  useEffect(() => setChecked(new Set()), [tab, wide, picked, q]);

  // Details for what the lists show, plus the paper picked on the chart (any
  // dot can be); the rest of the library is only dots.
  const infoIds = useMemo(() => {
    const s = new Set<string>(memberRows.map((m) => m.paper_id));
    for (const r of rows) if (r.related || r.suggested) s.add(r.paper_id);
    return [...s];
  }, [rows, memberRows]);
  const { data: infoList, isLoading: loadingInfo } = usePaperInfo(teamId, infoIds);
  const { data: pickedInfo } = usePaperInfo(
    teamId,
    selected && !infoIds.includes(selected) ? [selected] : [],
  );
  const info = useMemo(
    () => new Map([...(infoList ?? []), ...(pickedInfo ?? [])].map((p) => [p.id, p])),
    [infoList, pickedInfo],
  );

  const isNew = useCallback(
    (r: Closeness) =>
      r.suggested !== null && lastViewed !== undefined && (lastViewed === null || r.posted_at > lastViewed),
    [lastViewed],
  );

  const litFacet = hoverFacet ?? picked;
  const lit = useMemo(
    () =>
      litFacet
        ? new Set(rows.filter((r) => hasFacet(r, litFacet.kind, litFacet.key)).map((r) => r.paper_id))
        : null,
    [litFacet, rows],
  );

  const suggestedRows = useMemo(() => rows.filter((r) => r.suggested !== null), [rows]);
  const above = useMemo(() => rows.filter((r) => r.suggested === "close"), [rows]);

  const dots: Dot[] = useMemo(
    () =>
      rows
        .filter((r) => r.similarity !== null && r.year !== null && r.state !== "dismissed")
        .map((r) => ({
          id: r.paper_id,
          year: r.year as number,
          similarity: r.similarity as number,
          kind: r.state === "in" ? "in" : r.suggested ? (isNew(r) ? "new" : "suggested") : "other",
        })),
    [rows, isNew],
  );
  const cutoff = rows[0]?.cutoff ?? null;

  // --- the list ---
  const listIds: string[] = useMemo(
    () =>
      wide && picked
        ? rows
            .filter((r) => r.related && r.state === null && hasFacet(r, picked.kind, picked.key))
            .map((r) => r.paper_id)
        : tab === "in"
          ? inIds
          : suggestedRows.map((r) => r.paper_id),
    [wide, picked, rows, tab, inIds, suggestedRows],
  );
  const needle = q.trim().toLowerCase();
  const shown = useMemo(
    () =>
      listIds
        .filter((pid) => !picked || wide || hasFacet(byId.get(pid), picked.kind, picked.key))
        .filter((pid) => {
          if (!needle) return true;
          const p = info.get(pid);
          return !!p && `${p.title ?? ""} ${p.authors.join(" ")}`.toLowerCase().includes(needle);
        })
        .sort((a, b) => {
          const pa = info.get(a);
          const pb = info.get(b);
          if (sort === "close") return (byId.get(b)?.similarity ?? -2) - (byId.get(a)?.similarity ?? -2);
          if (sort === "year") return (pb?.year ?? 0) - (pa?.year ?? 0);
          if (sort === "title") return (pa?.title ?? "").localeCompare(pb?.title ?? "");
          const ta = memberOf.get(a)?.added_at ?? pa?.posted_at ?? "";
          const tb = memberOf.get(b)?.added_at ?? pb?.posted_at ?? "";
          return tb.localeCompare(ta);
        }),
    [listIds, picked, wide, byId, needle, info, sort, memberOf],
  );

  const saved = useMemo(() => new Set((reading ?? []).map((r) => r.paper_id)), [reading]);
  const unread = inIds.filter((pid) => !read?.has(pid)).length;

  const tags = useMemo(() => facetItems("tag", rows, follows ?? [], range), [rows, follows, range]);
  const labs = useMemo(() => facetItems("lab", rows, follows ?? [], range), [rows, follows, range]);
  const nRelated = rows.filter((r) => r.related).length;

  const onSelectDot = useCallback((pid: string) => setSelected((cur) => (cur === pid ? null : pid)), []);

  // --- actions ---
  /** Runs a write, refreshes, and offers Undo. Resolves true only if it saved,
   *  so callers chain follow-ups (clearing a selection) on success alone. */
  async function act(
    fn: () => Promise<void>,
    done?: { message: string; undo?: () => Promise<void> },
  ): Promise<boolean> {
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      toast({ message: err instanceof Error ? err.message : "Couldn’t save that. Try again." });
      setBusy(false);
      return false;
    }
    await refresh(project.id, teamId);
    setBusy(false);
    if (done)
      toast({
        message: done.message,
        actionLabel: done.undo ? "Undo" : undefined,
        // A failed undo throws: the toast stays and says so (components/Toast).
        onAction: done.undo
          ? async () => {
              await done.undo!();
              await refresh(project.id, teamId);
            }
          : undefined,
      });
    return true;
  }
  const papersWord = (n: number) => (n === 1 ? "1 paper" : `${n} papers`);
  const add = (ids: string[]) => {
    const prev = ids.filter((pid) => memberOf.get(pid)?.state === "dismissed");
    return act(() => setPapers(project.id, userId, ids, "in"), {
      message: `Added ${papersWord(ids.length)} to the project`,
      undo: async () => {
        await clearPapers(project.id, ids.filter((pid) => !prev.includes(pid)));
        await setPapers(project.id, userId, prev, "dismissed");
      },
    });
  };
  const dismiss = (ids: string[]) =>
    act(() => setPapers(project.id, userId, ids, "dismissed"), {
      message: `${papersWord(ids.length)} won’t be suggested again`,
      undo: () => clearPapers(project.id, ids),
    });
  const remove = (ids: string[]) =>
    act(() => clearPapers(project.id, ids), {
      message: `Removed ${papersWord(ids.length)} from the project`,
      undo: () => setPapers(project.id, userId, ids, "in"),
    });
  const bulk = (fn: (ids: string[]) => Promise<boolean>) => async () => {
    if (await fn([...checked])) setChecked(new Set());
  };
  const follow = (f: Facet, on: boolean) =>
    act(() => setFollow(project.id, { kind: f.kind, value: f.key }, on));
  const setLevel = (level: SuggestLevel) =>
    act(async () => void (await updateProject(project.id, { suggest_level: level })));

  async function onDelete() {
    const ok = await confirm({
      title: `Delete “${project.name}”?`,
      body: "The project goes for everyone it’s shared with. The papers stay in the library and on reading lists.",
      confirmLabel: "Delete project",
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteProject(project.id);
    } catch (err) {
      toast({ message: err instanceof Error ? err.message : "Couldn’t delete the project." });
      return;
    }
    // Leave first, so the page doesn't refetch a project that is gone.
    navigate("/projects");
    for (const key of ["project", "project-closeness", "project-papers", "project-follows"])
      qc.removeQueries({ queryKey: [key, project.id] });
    void qc.invalidateQueries({ queryKey: ["projects", teamId] });
    void qc.invalidateQueries({ queryKey: ["projects-by-paper", teamId] });
    toast({ message: `Deleted “${project.name}”` });
  }

  function exportBib() {
    const papers = inIds.map((pid) => info.get(pid)).filter((p): p is PaperInfo => !!p);
    const text = formatPapers(papers, "bibtex");
    downloadText(exportFilename("bibtex", papers.length, project.name), text, FORMAT_META.bibtex.mime);
  }

  /** A member's name, for avatars; `label` says "You" for the caller. */
  const nameOf = (uid: string | null) =>
    !uid ? null : (lab?.find((m) => m.user_id === uid)?.profiles?.display_name ?? null);
  const label = (uid: string | null) => (uid === userId ? "You" : nameOf(uid));
  const people = projectPeople(project);
  const sel = selected ? byId.get(selected) : undefined;
  const selInfo = selected ? info.get(selected) : undefined;
  const hov = hovered && hovered !== selected ? byId.get(hovered) : undefined;

  function why(r: Closeness | undefined): string {
    if (!r || r.similarity === null) return "Not embedded yet";
    const sim = `${Math.round(r.similarity * 100)}% similar`;
    if (r.suggested === "tag") return `From followed tag ${r.via}`;
    if (r.suggested === "lab") return `From the followed ${r.via} lab`;
    if (r.nearest_id) {
      const t = info.get(r.nearest_id)?.title;
      return t ? `${sim}, closest to “${t}”` : sim;
    }
    return `${sim} to the description`;
  }

  return (
    <div className="mx-auto flex max-w-[1240px] flex-col gap-6 p-6 lg:p-8">
      <nav aria-label="Breadcrumb" className="text-meta text-muted">
        <Link to="/projects" className="hover:text-fg hover:underline">
          Projects
        </Link>
        <span aria-hidden className="mx-1.5">
          /
        </span>
        <span className="text-fg">{project.name}</span>
      </nav>

      <header className="flex flex-wrap items-start gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <h1 className="text-display font-bold tracking-tight">{project.name}</h1>
          {project.description && <p className="max-w-3xl text-sm text-muted">{project.description}</p>}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-muted">
            <span className="flex -space-x-1.5">
              {people.slice(0, 5).map((u) => (
                <span key={u} title={label(u) ?? undefined} className="rounded-full ring-2 ring-bg">
                  <Avatar name={nameOf(u) ?? "?"} size={22} />
                </span>
              ))}
            </span>
            <span>{papersWord(inIds.length)}</span>
            {unread > 0 && <span>· {unread} unread</span>}
            <span>· Updated {formatRelative(project.updated_at)}</span>
            {!project.owner_id && <span>· Its owner has left the lab</span>}
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-meta text-muted">
            <span>Following</span>
            {(follows ?? []).length === 0 ? (
              <span className="text-faint">no tags or labs yet</span>
            ) : (
              (follows ?? []).map((f) => (
                <span
                  key={`${f.kind}:${f.value}`}
                  className={cn(
                    "rounded-full border border-border px-2 py-0.5 text-fg",
                    f.kind === "tag" && "font-mono text-[12px]",
                  )}
                >
                  {facetName({ kind: f.kind, key: f.value })}
                </span>
              ))
            )}
            <a href="#around-h" className="text-accent hover:underline">
              Edit
            </a>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={exportBib}
            disabled={inIds.length === 0}
            title="Download a BibTeX file of the papers in this project"
          >
            <Download size={14} aria-hidden />
            Export .bib
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setSharing(true)} aria-haspopup="dialog">
            {project.visibility === "private" ? <Lock size={14} aria-hidden /> : <Users size={14} aria-hidden />}
            {VISIBILITY[project.visibility].label}
          </Button>
          <Button size="sm" onClick={() => setAdding(true)}>
            <Plus size={14} aria-hidden />
            Add papers
          </Button>
          {canDelete && <MoreMenu canEdit={owner} onEdit={() => setEditing(true)} onDelete={onDelete} />}
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <label className="relative w-full max-w-xs">
          <span className="sr-only">Search this project</span>
          <Search size={14} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <Input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search titles and authors"
            className="pl-8"
          />
        </label>
        {picked && (
          <button
            type="button"
            onClick={() => {
              setPicked(null);
              setWide(false);
            }}
            aria-label={`Stop filtering by ${facetName(picked)}`}
            className="inline-flex h-8 items-center gap-1.5 rounded-full border border-accent bg-accent-weak px-3 text-xs font-medium text-accent"
          >
            {facetName(picked)}
            <X size={12} aria-hidden />
          </button>
        )}
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-12">
        <section aria-labelledby="closeness-h" className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4 lg:col-span-7">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <h2 id="closeness-h" className="text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
              Closeness to this project
            </h2>
            <div className="ml-auto flex items-center gap-2 text-meta text-muted">
              <span>Suggest</span>
              {owner ? (
                <Segmented
                  value={project.suggest_level}
                  onChange={setLevel}
                  label="How many papers to suggest"
                  options={LEVELS}
                />
              ) : (
                <span className="text-fg">{LEVELS.find((l) => l.value === project.suggest_level)?.label}</span>
              )}
            </div>
          </div>
          <ChartLegend />
          {loadingCloseness ? (
            <div className="h-[300px] animate-pulse rounded bg-surface-2" />
          ) : dots.length === 0 ? (
            <p className="grid h-[300px] place-items-center text-center text-sm text-muted">
              Nothing to plot yet: add papers, or describe the project, and the library’s papers appear by how close they are.
            </p>
          ) : (
            <div className="relative">
              <ClosenessChart
                dots={dots}
                cutoff={cutoff}
                lit={lit}
                hovered={hovered}
                selected={selected}
                onHover={setHovered}
                onSelect={onSelectDot}
                label={`Library papers by year and closeness to ${project.name}. ${inIds.length} in the project, ${suggestedRows.length} suggested. The lists beside it hold the same papers.`}
              />
              {hov && (
                <div className="pointer-events-none absolute left-12 top-2 max-w-sm rounded-control border border-border bg-surface px-3 py-2 text-xs shadow-lg">
                  <div className="font-medium text-fg">{info.get(hov.paper_id)?.title ?? "A library paper"}</div>
                  <div className="tabular-nums text-muted">
                    {hov.year} · {hov.similarity !== null ? `${Math.round(hov.similarity * 100)}% similar` : ""}
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 text-meta text-muted">
            <span>
              {above.length === 0
                ? "Nothing above the line yet."
                : `${papersWord(above.length)} above the line, not in the project.`}
            </span>
            {above.length > 0 && (
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => add(above.map((r) => r.paper_id))} className="ml-auto">
                <Plus size={14} aria-hidden />
                Add all {above.length}
              </Button>
            )}
          </div>
          {sel && (
            <div role="region" aria-label="Selected paper" className="mt-1 flex flex-col gap-1.5 rounded-control border border-border bg-surface-2 p-3">
              <div className="flex items-start gap-2">
                <button
                  type="button"
                  onClick={() => openPaper(sel.paper_id)}
                  className="min-w-0 flex-1 text-left text-sm font-semibold text-fg hover:underline"
                >
                  {selInfo?.title ?? "A library paper"}
                </button>
                <button
                  type="button"
                  aria-label="Close"
                  onClick={() => setSelected(null)}
                  className="grid h-6 w-6 place-items-center rounded-control text-faint hover:text-fg"
                >
                  <X size={14} aria-hidden />
                </button>
              </div>
              {selInfo && (
                <div className="text-meta text-muted">
                  {formatAuthors(selInfo.authors)} · {selInfo.venue ?? ""} {selInfo.year ?? ""}
                </div>
              )}
              <div className="text-meta text-muted">{why(sel)}</div>
              <div className="flex flex-wrap gap-2">
                {sel.state === null && (
                  <>
                    <Button size="sm" disabled={busy} onClick={() => add([sel.paper_id])}>
                      Add to project
                    </Button>
                    <Button variant="secondary" size="sm" disabled={busy} onClick={() => dismiss([sel.paper_id])}>
                      Not relevant
                    </Button>
                  </>
                )}
                {sel.state === "in" && (
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => remove([sel.paper_id])}>
                    Remove from project
                  </Button>
                )}
                <BookmarkButton
                  paperId={sel.paper_id}
                  teamId={teamId}
                  userId={userId}
                  bookmarked={saved.has(sel.paper_id)}
                  showLabel
                />
              </div>
            </div>
          )}
        </section>

        <section aria-label="Papers" className="flex flex-col rounded-card border border-border bg-surface lg:col-span-5">
          {checked.size > 0 ? (
            <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
              <span className="text-sm tabular-nums">{checked.size} selected</span>
              {(tab === "suggested" || wide) && (
                <Button size="sm" disabled={busy} onClick={bulk(add)}>
                  Add to project
                </Button>
              )}
              {(tab === "suggested" || wide) && (
                <Button variant="secondary" size="sm" disabled={busy} onClick={bulk(dismiss)}>
                  Not relevant
                </Button>
              )}
              {tab === "in" && !wide && (
                <Button variant="secondary" size="sm" disabled={busy} onClick={bulk(remove)}>
                  Remove
                </Button>
              )}
              <button
                type="button"
                aria-label="Clear selection"
                onClick={() => setChecked(new Set())}
                className="ml-auto grid h-7 w-7 place-items-center rounded-control text-faint hover:text-fg"
              >
                <X size={14} aria-hidden />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 border-b border-border px-3 pt-2">
              <div role="tablist" aria-label="Papers" className="flex">
                {(
                  [
                    ["in", "In project", inIds.length],
                    ["suggested", "Suggested", suggestedRows.length],
                  ] as const
                ).map(([value, label, n]) => (
                  <button
                    key={value}
                    type="button"
                    role="tab"
                    aria-selected={tab === value && !wide}
                    onClick={() => {
                      setTab(value);
                      setWide(false);
                    }}
                    className={cn(
                      "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition",
                      tab === value && !wide ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg",
                    )}
                  >
                    {label} <span className="tabular-nums text-faint">{n}</span>
                  </button>
                ))}
              </div>
              <label className="ml-auto pb-1.5">
                <span className="sr-only">Sort</span>
                <select
                  value={sort}
                  onChange={(e) => setSort(e.target.value as Sort)}
                  className="h-8 rounded-control border border-border bg-surface px-2 text-xs text-fg"
                >
                  {SORTS.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          {wide && picked && (
            <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-4 py-2 text-meta text-muted">
              <span className="flex-1">
                {papersWord(listIds.length)} close to the project {picked.kind === "tag" ? `tagged ${picked.key}` : `from the ${facetName(picked)}`}, not in it
              </span>
              <button
                type="button"
                aria-label="Back to suggestions"
                onClick={() => setWide(false)}
                className="grid h-6 w-6 place-items-center rounded-control text-faint hover:text-fg"
              >
                <X size={14} aria-hidden />
              </button>
            </div>
          )}
          <ul className="max-h-[560px] flex-1 overflow-auto" onMouseLeave={() => setHovered(null)}>
            {loadingInfo && shown.length === 0 && listIds.length > 0 ? (
              <li className="p-4 text-sm text-muted">Loading…</li>
            ) : shown.length === 0 ? (
              <li className="p-6 text-center text-sm text-muted">
                {needle || picked
                  ? "No papers match."
                  : tab === "in"
                    ? "No papers yet. Add some from Suggested, or with Add papers."
                    : "No suggestions right now."}
              </li>
            ) : (
              shown.map((pid) => {
                const p = info.get(pid);
                const r = byId.get(pid);
                const m = memberOf.get(pid);
                const inProject = m?.state === "in";
                const sim = r?.similarity ?? null;
                return (
                  <li
                    key={pid}
                    onMouseEnter={() => setHovered(pid)}
                    className={cn(
                      "flex items-start gap-2.5 border-b border-border px-3 py-2.5 last:border-b-0",
                      (hovered === pid || selected === pid) && "bg-surface-2",
                    )}
                  >
                    <SelectCheckbox
                      checked={checked.has(pid)}
                      onChange={() =>
                        setChecked((prev) => {
                          const next = new Set(prev);
                          if (next.has(pid)) next.delete(pid);
                          else next.add(pid);
                          return next;
                        })
                      }
                      label={`Select ${p?.title ?? "paper"}`}
                      className="mt-0.5"
                    />
                    <span
                      aria-label={read?.has(pid) ? undefined : "Unread"}
                      className={cn("mt-2 h-1.5 w-1.5 shrink-0 rounded-full", read?.has(pid) ? "bg-transparent" : "bg-accent")}
                    />
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <button
                        type="button"
                        onClick={() => openPaper(pid)}
                        className="text-left text-sm font-medium leading-snug text-fg hover:underline"
                      >
                        {p?.title ?? "Untitled paper"}
                      </button>
                      <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                        {p?.venue && (
                          <span className="max-w-[16rem] truncate font-semibold uppercase tracking-wide">{p.venue}</span>
                        )}
                        {p?.year != null && <span>· {p.year}</span>}
                        {isPreprintVenue(p?.venue ?? null) && <PreprintBadge />}
                        {r && isNew(r) && <span className="font-semibold text-accent">New</span>}
                      </span>
                      <span className="flex items-center gap-2 text-[11.5px] text-faint">
                        {sim !== null && (
                          <span aria-hidden className="relative h-1 w-10 shrink-0 rounded-full bg-surface-3">
                            <span
                              className="absolute inset-y-0 left-0 rounded-full bg-accent"
                              style={{ width: `${Math.max(0, Math.min(1, sim)) * 100}%` }}
                            />
                          </span>
                        )}
                        <span className="truncate">{why(r)}</span>
                      </span>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {inProject && m && (
                        <span className="flex items-center gap-1 text-[11px] tabular-nums text-faint" title={`Added by ${label(m.added_by) ?? "someone"}`}>
                          <Avatar name={nameOf(m.added_by) ?? "?"} size={18} />
                          {formatAgo(m.added_at)}
                        </span>
                      )}
                      {!inProject && (
                        <>
                          <IconButton label="Add to project" disabled={busy} onClick={() => add([pid])}>
                            <Plus size={15} aria-hidden />
                          </IconButton>
                          <IconButton label="Not relevant to this project" disabled={busy} onClick={() => dismiss([pid])}>
                            <X size={15} aria-hidden />
                          </IconButton>
                        </>
                      )}
                      <BookmarkButton paperId={pid} teamId={teamId} userId={userId} bookmarked={saved.has(pid)} />
                    </div>
                  </li>
                );
              })
            )}
          </ul>
          {dismissedIds.length > 0 && (
            <div className="border-t border-border px-4 py-2 text-meta text-muted">
              <button type="button" onClick={() => setShowDismissed((v) => !v)} className="hover:text-fg hover:underline" aria-expanded={showDismissed}>
                {papersWord(dismissedIds.length)} marked not relevant · {showDismissed ? "Hide" : "Show"}
              </button>
              {showDismissed && (
                <ul className="mt-2 flex flex-col gap-1">
                  {dismissedIds.map((pid) => (
                    <li key={pid} className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-fg">{info.get(pid)?.title ?? "A library paper"}</span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => act(() => clearPapers(project.id, [pid]))}
                        className="shrink-0 text-accent hover:underline"
                      >
                        Bring back
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      </div>

      <AroundProject
        tags={tags}
        labs={labs}
        nRelated={nRelated}
        range={range}
        onRange={setRange}
        picked={picked}
        onPick={(f) => {
          setPicked(f);
          setWide(false);
        }}
        onHover={setHoverFacet}
        onFollow={follow}
        onGap={(f) => {
          setPicked(f);
          setWide(true);
        }}
        loading={loadingCloseness || loadingInfo}
      />

      <ProjectDialog
        open={editing}
        onClose={() => setEditing(false)}
        teamId={teamId}
        project={project}
        onSaved={() => void refresh(project.id, teamId)}
      />
      <ShareDialog
        open={sharing}
        onClose={() => setSharing(false)}
        project={project}
        teamId={teamId}
        userId={userId}
        onChanged={() => void refresh(project.id, teamId)}
      />
      <AddPapersDialog
        open={adding}
        onClose={() => setAdding(false)}
        teamId={teamId}
        teamName={teamName}
        exclude={inIds}
        onAdd={(paper) => add([paper.id])}
      />
      {confirmDialog}
    </div>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-7 w-7 place-items-center rounded-control text-muted transition hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function MoreMenu({
  canEdit,
  onEdit,
  onDelete,
}: {
  canEdit: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useDismissable(ref, open, (reason) => {
    setOpen(false);
    if (reason === "escape") trigger.current?.focus();
  });
  return (
    <div ref={ref} className="relative">
      <button
        ref={trigger}
        type="button"
        aria-label="More: edit or delete the project"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="grid h-8 w-8 place-items-center rounded-control text-muted hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <MoreHorizontal size={16} aria-hidden />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-9 z-20 flex w-52 flex-col rounded-control border border-border bg-surface p-1 shadow-lg">
          {canEdit && (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onEdit();
              }}
              className="rounded-control px-3 py-2 text-left text-sm hover:bg-surface-2"
            >
              Edit name and description
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onDelete();
            }}
            className="rounded-control px-3 py-2 text-left text-sm text-danger hover:bg-surface-2"
          >
            Delete project
          </button>
        </div>
      )}
    </div>
  );
}

function AddPapersDialog({
  open,
  onClose,
  teamId,
  teamName,
  exclude,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  teamId: string;
  teamName: string;
  exclude: string[];
  /** Resolves true once the paper is saved in the project. */
  onAdd: (p: PickedPaper) => Promise<boolean>;
}) {
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<string[]>([]);
  useEffect(() => {
    if (open) setAdded([]);
  }, [open]);
  return (
    <Modal open={open} onClose={onClose} label="Add papers to the project" className="max-w-[560px]">
      <div className="flex flex-col gap-3 p-6 pt-12">
        <h2 className="text-heading font-semibold">Add papers</h2>
        <p className="text-sm text-muted">
          Search {teamName}’s library by title, abstract or author. Each one you pick goes straight in.
        </p>
        <PaperPicker
          teamId={teamId}
          value={null}
          exclude={[...exclude, ...added]}
          busy={busy}
          autoFocus
          onChange={async (p) => {
            if (!p) return;
            setBusy(true);
            try {
              if (await onAdd(p)) setAdded((a) => [...a, p.id]);
            } finally {
              setBusy(false);
            }
          }}
        />
        {added.length > 0 && (
          <p className="text-meta text-muted">
            Added {added.length === 1 ? "1 paper" : `${added.length} papers`}.
          </p>
        )}
        <div className="flex justify-end">
          <Button size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </Modal>
  );
}
