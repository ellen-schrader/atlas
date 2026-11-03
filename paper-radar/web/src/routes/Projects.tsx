import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueries, useQuery } from "@tanstack/react-query";
import { FolderOpen, Lock, Plus, Radar, Search, Users, X } from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { Segmented } from "@/components/home/HomeSection";
import { usePaperModal } from "@/components/PaperModal";
import { ClosenessChart, type Dot } from "@/components/projects/ClosenessChart";
import { ProjectDialog } from "@/components/projects/ProjectDialogs";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useMembers } from "@/hooks/useMembers";
import { usePaperInfo, useProjectCounts, useProjectList, useRefreshProject } from "@/hooks/useProjects";
import {
  type Closeness,
  PROJECTS_FEATURE,
  type Project,
  VISIBILITY,
  projectCloseness,
  projectPeople,
  setPapers,
} from "@/lib/projects";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/** What a project will do, one line each. */
const COMING = [
  { icon: FolderOpen, text: "Keep the papers for one piece of work together, without adding them to your reading list." },
  { icon: Radar, text: "See how close each library paper is to the project, and what has arrived nearby." },
  { icon: Users, text: "Share it with the whole lab, a few people, or keep it to yourself." },
];

/** /projects: the projects index for anyone with the feature, and a locked
 *  placeholder for everyone else while it is dark. Topic maps and the figure
 *  gallery were retired to make room; their old URLs redirect here. */
export default function Projects() {
  const { features, featuresLoaded } = useAppContext();
  useDocumentTitle("Projects");
  if (!featuresLoaded) return null;
  return features.includes(PROJECTS_FEATURE) ? <ProjectsIndex /> : <Locked />;
}

function Locked() {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-display font-bold tracking-tight">Projects</h1>
        <p className="mt-1.5 text-sm text-muted">Coming soon.</p>
      </div>

      <section
        aria-labelledby="projects-soon"
        className="flex flex-col gap-5 rounded-card border border-border bg-surface p-6 sm:p-8"
      >
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-surface-2 text-accent">
            <Lock size={18} aria-hidden />
          </span>
          <h2 id="projects-soon" className="text-lg font-semibold tracking-tight">
            Projects are on their way
          </h2>
        </div>
        <ul className="flex flex-col gap-3">
          {COMING.map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-start gap-3 text-sm text-fg">
              <Icon size={16} aria-hidden className="mt-0.5 shrink-0 text-muted" />
              {text}
            </li>
          ))}
        </ul>
        <p className="border-t border-border pt-4 text-meta text-faint">
          Topic maps and the figure gallery have been retired to make room for this.
        </p>
      </section>
    </div>
  );
}

type Scope = "all" | "mine" | "shared";

function ProjectsIndex() {
  const { team, userId } = useAppContext();
  const navigate = useNavigate();
  const toast = useToast();
  const refresh = useRefreshProject();
  const { openPaper } = usePaperModal();
  const { data: projects, isLoading, isError } = useProjectList(team.id);
  const { data: members } = useMembers(team.id);
  const [scope, setScope] = useState<Scope>("all");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const list = projects ?? [];
  // One closeness query per project, shared with its page through the cache:
  // the cards' charts and "New suggestions" both read it. Each is a pass over
  // the library in Postgres, fine for a lab's handful of projects.
  const closeness = useQueries({
    queries: list.map((p) => ({
      queryKey: ["project-closeness", p.id],
      queryFn: () => projectCloseness(p.id),
      staleTime: 60_000,
    })),
  });
  const { data: counts } = useProjectCounts(list.map((p) => p.id));
  const { data: views } = useQuery({
    queryKey: ["project-views", team.id, userId],
    queryFn: async (): Promise<Map<string, string>> => {
      const { data, error } = await supabase
        .from("project_views")
        .select("project_id, last_viewed_at")
        .eq("user_id", userId);
      if (error) throw error;
      return new Map((data ?? []).map((v) => [v.project_id as string, v.last_viewed_at as string]));
    },
  });

  const isNew = (p: Project, r: Closeness) => {
    if (!r.suggested || !views) return false;
    const seen = views.get(p.id);
    return !seen || r.posted_at > seen;
  };

  // "New suggestions" across every project, closest first.
  const fresh = useMemo(() => {
    const out: { project: Project; row: Closeness }[] = [];
    list.forEach((p, i) => {
      for (const r of closeness[i]?.data ?? []) if (isNew(p, r)) out.push({ project: p, row: r });
    });
    return out
      .filter((f) => !hidden.has(`${f.project.id}:${f.row.paper_id}`))
      .sort((a, b) => (b.row.similarity ?? 0) - (a.row.similarity ?? 0))
      .slice(0, 8);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, closeness.map((c) => c.dataUpdatedAt).join(), views, hidden]);
  const nFresh = list.reduce(
    (n, p, i) => n + (closeness[i]?.data ?? []).filter((r) => isNew(p, r)).length,
    0,
  );
  const { data: freshInfo } = usePaperInfo(team.id, fresh.map((f) => f.row.paper_id));
  const titleOf = new Map((freshInfo ?? []).map((p) => [p.id, p]));

  const nameOf = (uid: string) => members?.find((m) => m.user_id === uid)?.profiles?.display_name ?? "?";
  const mine = list.filter((p) => p.owner_id === userId);
  const shared = list.filter((p) => p.owner_id !== userId);
  const needle = q.trim().toLowerCase();
  const shown = (scope === "mine" ? mine : scope === "shared" ? shared : list).filter(
    (p) => !needle || `${p.name} ${p.description}`.toLowerCase().includes(needle),
  );

  async function decide(project: Project, paperId: string, state: "in" | "dismissed") {
    const key = `${project.id}:${paperId}`;
    setHidden((h) => new Set(h).add(key));
    try {
      await setPapers(project.id, userId, [paperId], state);
      await refresh(project.id, team.id);
      toast({ message: state === "in" ? `Added to ${project.name}` : "It won’t be suggested again" });
    } catch (err) {
      setHidden((h) => {
        const next = new Set(h);
        next.delete(key);
        return next;
      });
      toast({ message: err instanceof Error ? err.message : "Couldn’t save that. Try again." });
    }
  }

  return (
    <div className="mx-auto flex max-w-[1240px] flex-col gap-6 p-6 lg:p-8">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-display font-bold tracking-tight">Projects</h1>
        <label className="relative ml-auto w-full max-w-xs">
          <span className="sr-only">Search projects</span>
          <Search size={14} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <Input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search projects"
            className="pl-8"
          />
        </label>
        <Button onClick={() => setCreating(true)}>
          <Plus size={15} aria-hidden />
          New project
        </Button>
      </header>

      {isError ? (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load your projects. Check your connection and reload.
        </p>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <section aria-labelledby="pj-h" className="flex min-w-0 flex-col gap-3">
            <div className="flex items-center gap-3">
              <h2 id="pj-h" className="text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
                Projects
              </h2>
              <Segmented
                value={scope}
                onChange={setScope}
                label="Which projects"
                options={[
                  { value: "all", label: `All ${list.length}` },
                  { value: "mine", label: `Mine ${mine.length}` },
                  { value: "shared", label: `Shared with me ${shared.length}` },
                ]}
              />
            </div>
            {isLoading ? (
              <div className="grid gap-4 sm:grid-cols-2">
                {Array.from({ length: 2 }).map((_, i) => (
                  <div key={i} className="h-56 animate-pulse rounded-card bg-surface-2" />
                ))}
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                {shown.map((p) => {
                  const i = list.indexOf(p);
                  const rows = closeness[i]?.data;
                  const nIn = counts?.get(p.id) ?? 0;
                  const nNew = (rows ?? []).filter((r) => isNew(p, r)).length;
                  const people = projectPeople(p);
                  return (
                    <Link
                      key={p.id}
                      to={`/projects/${p.id}`}
                      className="group flex flex-col overflow-hidden rounded-card border border-border bg-surface transition hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      <span className="relative block border-b border-border bg-surface-2/40 px-2 pt-2">
                        <ClosenessChart
                          mini
                          height={84}
                          dots={(rows ?? [])
                            .filter((r) => r.similarity !== null && r.year !== null && r.state !== "dismissed")
                            .map(
                              (r): Dot => ({
                                id: r.paper_id,
                                year: r.year as number,
                                similarity: r.similarity as number,
                                kind: r.state === "in" ? "in" : r.suggested ? (isNew(p, r) ? "new" : "suggested") : "other",
                              }),
                            )}
                          cutoff={rows?.[0]?.cutoff ?? null}
                          label={`${p.name}: its papers and suggestions by year and closeness`}
                        />
                        {nNew > 0 && (
                          <span className="absolute right-2 top-2 rounded-full bg-accent px-2 py-0.5 text-[11px] font-semibold tabular-nums text-accent-fg">
                            {nNew} new suggested
                          </span>
                        )}
                      </span>
                      <span className="flex flex-col gap-1.5 p-4">
                        <span className="text-base font-semibold text-fg group-hover:underline">{p.name}</span>
                        {p.description && <span className="line-clamp-2 text-meta text-muted">{p.description}</span>}
                        <span className="mt-1 flex items-center gap-2 text-meta tabular-nums text-muted">
                          <span className="flex -space-x-1.5">
                            {people.slice(0, 4).map((u) => (
                              <span key={u} title={u === userId ? "You" : nameOf(u)} className="rounded-full ring-2 ring-surface">
                                <Avatar name={nameOf(u)} size={20} />
                              </span>
                            ))}
                          </span>
                          <span>{nIn === 1 ? "1 paper" : `${nIn} papers`}</span>
                          <span className="ml-auto inline-flex items-center gap-1" title={VISIBILITY[p.visibility].sub}>
                            {p.visibility === "private" ? <Lock size={12} aria-hidden /> : <Users size={12} aria-hidden />}
                            {VISIBILITY[p.visibility].label}
                          </span>
                        </span>
                      </span>
                    </Link>
                  );
                })}
                <button
                  type="button"
                  onClick={() => setCreating(true)}
                  className="flex min-h-56 flex-col items-center justify-center gap-2 rounded-card border border-dashed border-border-strong p-6 text-center text-muted transition hover:border-accent hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  <Plus size={20} aria-hidden />
                  <span className="text-sm font-semibold">New project</span>
                  <span className="text-meta">Name it, describe it in a sentence, and Atlas suggests papers from the library.</span>
                </button>
              </div>
            )}
            <p className="text-meta text-faint">
              Each card plots the project’s papers and suggestions by year (across) and closeness (up). The shaded
              corner is recent and close.
            </p>
          </section>

          <section aria-labelledby="nn-h" className="flex h-fit flex-col rounded-card border border-border bg-surface">
            <div className="flex items-baseline gap-2 border-b border-border px-4 py-3">
              <h2 id="nn-h" className="text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
                New suggestions
              </h2>
              <span className="text-meta tabular-nums text-fg">{nFresh}</span>
              <span className="ml-auto text-meta text-faint">Since you last looked</span>
            </div>
            {fresh.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-muted">Nothing new near your projects.</p>
            ) : (
              <ul>
                {fresh.map(({ project, row }) => {
                  const p = titleOf.get(row.paper_id);
                  return (
                    <li key={`${project.id}:${row.paper_id}`} className="flex items-start gap-2 border-b border-border px-4 py-2.5 last:border-b-0">
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <button
                          type="button"
                          onClick={() => openPaper(row.paper_id)}
                          className="text-left text-sm font-medium leading-snug text-fg hover:underline"
                        >
                          {p?.title ?? "A library paper"}
                        </button>
                        <span className="text-[11.5px] tabular-nums text-faint">
                          {row.similarity !== null && `${Math.round(row.similarity * 100)}% similar to `}
                          <button
                            type="button"
                            onClick={() => navigate(`/projects/${project.id}`)}
                            className="font-medium text-muted hover:text-fg hover:underline"
                          >
                            {project.name}
                          </button>
                        </span>
                      </div>
                      <button
                        type="button"
                        aria-label={`Add to ${project.name}`}
                        title={`Add to ${project.name}`}
                        onClick={() => void decide(project, row.paper_id, "in")}
                        className="grid h-7 w-7 shrink-0 place-items-center rounded-control text-muted hover:bg-surface-2 hover:text-fg"
                      >
                        <Plus size={15} aria-hidden />
                      </button>
                      <button
                        type="button"
                        aria-label="Not relevant"
                        title="Not relevant"
                        onClick={() => void decide(project, row.paper_id, "dismissed")}
                        className={cn(
                          "grid h-7 w-7 shrink-0 place-items-center rounded-control text-muted hover:bg-surface-2 hover:text-fg",
                        )}
                      >
                        <X size={15} aria-hidden />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      )}

      <ProjectDialog
        open={creating}
        onClose={() => setCreating(false)}
        teamId={team.id}
        onSaved={(p) => {
          void refresh(p.id, team.id);
          navigate(`/projects/${p.id}`);
        }}
      />
    </div>
  );
}
