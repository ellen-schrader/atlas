import { useEffect, useRef, useState } from "react";
import { Check, FolderPlus, Plus } from "lucide-react";

import { ProjectDialog } from "@/components/projects/ProjectDialogs";
import { useToast } from "@/components/Toast";
import { useDismissable } from "@/hooks/useDismissable";
import { useFeatures } from "@/hooks/useFeatures";
import { useProjectList, useProjectsByPaper, useRefreshProject } from "@/hooks/useProjects";
import { PROJECTS_FEATURE, type Project, clearPapers, setPapers } from "@/lib/projects";
import { cn } from "@/lib/utils";

/** What a list that already holds the projects and memberships hands each row,
 *  so a long list doesn't run three queries per row. */
export interface ProjectsShared {
  projects: Project[];
  /** The projects this paper is in; undefined while not known yet. */
  inProjects: string[] | undefined;
}

/** "Add to project": tick the projects a paper belongs in, or start a new one
 *  with it. Independent of the bookmark, so adding a paper to a project never
 *  saves it to the reading list. Nothing renders without the projects feature.
 *  A disclosure of toggle buttons, not an ARIA menu: Tab moves through it. */
export function AddToProject({
  paperId,
  teamId,
  userId,
  shared,
  showLabel = false,
  className,
  align = "right",
}: {
  paperId: string;
  teamId: string;
  userId: string;
  /** From the list around it; when absent the button asks for itself. */
  shared?: ProjectsShared;
  showLabel?: boolean;
  className?: string;
  align?: "left" | "right";
}) {
  const { features } = useFeatures(teamId);
  const on = shared !== undefined || features.includes(PROJECTS_FEATURE);
  const own = on && shared === undefined;
  const { data: ownProjects } = useProjectList(teamId, own);
  const { data: ownByPaper } = useProjectsByPaper(teamId, [paperId], own);
  const projects = shared?.projects ?? ownProjects ?? [];
  const known = shared ? shared.inProjects : ownByPaper?.has(paperId) ? ownByPaper.get(paperId) : undefined;
  const refresh = useRefreshProject();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useDismissable(ref, open, (reason) => {
    setOpen(false);
    if (reason === "escape") trigger.current?.focus();
  });
  useEffect(() => {
    if (open) panel.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [open]);

  if (!on) return null;
  // Only projects still in the list count, so a deleted one never lingers.
  const visibleIds = new Set(projects.map((p) => p.id));
  const inProjects = new Set((known ?? []).filter((id) => visibleIds.has(id)));
  const n = inProjects.size;
  const label = n === 0 ? "Add to project" : n === 1 ? "In 1 project" : `In ${n} projects`;

  async function toggle(projectId: string, name: string) {
    if (known === undefined) return;
    const was = inProjects.has(projectId);
    setBusy(projectId);
    try {
      if (was) await clearPapers(projectId, [paperId]);
      else await setPapers(projectId, userId, [paperId], "in");
      await refresh(projectId, teamId);
      toast({ message: was ? `Removed from ${name}` : `Added to ${name}` });
    } catch (err) {
      toast({ message: err instanceof Error ? err.message : "Couldn’t save that. Try again." });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div ref={ref} className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-label={showLabel ? undefined : label}
        title={label}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-1.5 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          n > 0 ? "text-accent" : "text-muted hover:text-fg",
          className,
        )}
      >
        <FolderPlus size={15} aria-hidden />
        {showLabel && <span>{label}</span>}
      </button>
      {open && (
        <div
          ref={panel}
          role="group"
          aria-label="Projects for this paper"
          className={cn(
            "absolute top-full z-30 mt-1 flex w-64 flex-col rounded-control border border-border bg-surface p-1 shadow-lg",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {projects.length === 0 && <p className="px-3 py-2 text-meta text-muted">No projects yet.</p>}
          {projects.map((p) => {
            const ticked = inProjects.has(p.id);
            return (
              <button
                key={p.id}
                type="button"
                aria-pressed={ticked}
                disabled={busy !== null || known === undefined}
                onClick={() => void toggle(p.id, p.name)}
                className="flex items-center gap-2 rounded-control px-3 py-2 text-left text-sm hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
              >
                <span
                  aria-hidden
                  className={cn(
                    "grid h-4 w-4 shrink-0 place-items-center rounded border",
                    ticked ? "border-accent bg-accent text-accent-fg" : "border-border-strong",
                  )}
                >
                  {ticked && <Check size={11} strokeWidth={3} />}
                </span>
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              setCreating(true);
            }}
            className="mt-1 flex items-center gap-2 border-t border-border px-3 pb-1 pt-2 text-left text-meta font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <Plus size={13} aria-hidden />
            New project with this paper
          </button>
        </div>
      )}
      <ProjectDialog
        open={creating}
        onClose={() => setCreating(false)}
        teamId={teamId}
        onSaved={async (p) => {
          try {
            await setPapers(p.id, userId, [paperId], "in");
            toast({ message: `Started ${p.name} with this paper` });
          } catch (err) {
            toast({ message: err instanceof Error ? err.message : "Created the project, but couldn’t add the paper." });
          }
          await refresh(p.id, teamId);
        }}
      />
    </div>
  );
}
