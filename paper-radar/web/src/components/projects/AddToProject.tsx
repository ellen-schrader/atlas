import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Check, FolderPlus } from "lucide-react";

import { useToast } from "@/components/Toast";
import { useDismissable } from "@/hooks/useDismissable";
import { useFeatures } from "@/hooks/useFeatures";
import { useProjectList, useProjectsByPaper, useRefreshProject } from "@/hooks/useProjects";
import { PROJECTS_FEATURE, clearPapers, setPapers } from "@/lib/projects";
import { cn } from "@/lib/utils";

/** "Add to project": tick the projects a paper belongs in. Independent of the
 *  bookmark, so adding a paper to a project never saves it to the reading
 *  list. Nothing renders without the projects feature. */
export function AddToProject({
  paperId,
  teamId,
  userId,
  showLabel = false,
  className,
  align = "right",
}: {
  paperId: string;
  teamId: string;
  userId: string;
  showLabel?: boolean;
  className?: string;
  align?: "left" | "right";
}) {
  const { features } = useFeatures(teamId);
  const on = features.includes(PROJECTS_FEATURE);
  const { data: projects } = useProjectList(teamId, on);
  const { data: byPaper } = useProjectsByPaper(teamId, on);
  const refresh = useRefreshProject();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useDismissable(ref, open, (reason) => {
    setOpen(false);
    if (reason === "escape") trigger.current?.focus();
  });

  if (!on) return null;
  const inProjects = new Set(byPaper?.get(paperId) ?? []);
  const n = inProjects.size;
  const label = n === 0 ? "Add to project" : n === 1 ? "In 1 project" : `In ${n} projects`;

  async function toggle(projectId: string, name: string) {
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
        aria-haspopup="menu"
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
          role="menu"
          aria-label="Projects"
          className={cn(
            "absolute top-full z-30 mt-1 flex w-64 flex-col rounded-control border border-border bg-surface p-1 shadow-lg",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {(projects ?? []).length === 0 ? (
            <p className="px-3 py-2 text-meta text-muted">No projects yet.</p>
          ) : (
            (projects ?? []).map((p) => {
              const ticked = inProjects.has(p.id);
              return (
                <button
                  key={p.id}
                  type="button"
                  role="menuitemcheckbox"
                  aria-checked={ticked}
                  disabled={busy !== null}
                  onClick={() => void toggle(p.id, p.name)}
                  className="flex items-center gap-2 rounded-control px-3 py-2 text-left text-sm hover:bg-surface-2 disabled:opacity-60"
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
              )
            })
          )}
          <Link
            to="/projects?new=1"
            onClick={() => setOpen(false)}
            className="mt-1 border-t border-border px-3 pb-1 pt-2 text-meta text-accent hover:underline"
          >
            New project…
          </Link>
        </div>
      )}
    </div>
  );
}
