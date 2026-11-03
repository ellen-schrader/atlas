import { type FormEvent, useEffect, useState } from "react";
import { X } from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Modal } from "@/components/ui/modal";
import { Textarea } from "@/components/ui/textarea";
import { useMembers } from "@/hooks/useMembers";
import { type ProjectRow, createProject, updateProject } from "@/lib/api";
import { type Project, VISIBILITY, type Visibility, setPerson } from "@/lib/projects";
import { cn } from "@/lib/utils";

/** New project, or edit one's name and description (the owner only). */
export function ProjectDialog({
  open,
  onClose,
  teamId,
  project,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  teamId: string;
  /** Editing this one; a new project when absent. */
  project?: Project;
  onSaved: (p: ProjectRow) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<Visibility>("private");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(project?.name ?? "");
    setDescription(project?.description ?? "");
    setVisibility(project?.visibility ?? "private");
    setError(null);
  }, [open, project]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const saved = project
        ? await updateProject(project.id, { name, description })
        : await createProject(teamId, { name, description, visibility });
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t save the project.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} label={project ? "Edit project" : "New project"} className="max-w-[520px]">
      <form onSubmit={submit} className="flex flex-col gap-4 p-6 pt-12">
        <h2 className="text-heading font-semibold">{project ? "Edit project" : "New project"}</h2>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="project-name">Name</Label>
          <Input
            id="project-name"
            value={name}
            maxLength={120}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            placeholder="TLS and B cells in breast cancer"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="project-desc">What it’s about</Label>
          <Textarea
            id="project-desc"
            rows={3}
            maxLength={400}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="One or two sentences. Atlas uses them to suggest papers until the project has three."
          />
        </div>
        {!project && (
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1.5 text-xs font-medium tracking-wide text-muted">Who can see it</legend>
            <VisibilityOptions value={visibility} onChange={setVisibility} />
            {visibility === "people" && (
              <p className="text-meta text-muted">You can pick the people once it’s created.</p>
            )}
          </fieldset>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !name.trim()}>
            {busy ? "Saving…" : project ? "Save" : "Create project"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function VisibilityOptions({
  value,
  onChange,
  disabled,
}: {
  value: Visibility;
  onChange: (v: Visibility) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      {(Object.keys(VISIBILITY) as Visibility[]).map((v) => (
        <label
          key={v}
          className={cn(
            "flex cursor-pointer items-start gap-2.5 rounded-control border px-3 py-2 transition",
            value === v ? "border-accent bg-accent-weak" : "border-border hover:border-border-strong",
            disabled && "cursor-default opacity-70",
          )}
        >
          <input
            type="radio"
            name="visibility"
            className="mt-1 accent-[var(--accent)]"
            checked={value === v}
            disabled={disabled}
            onChange={() => onChange(v)}
          />
          <span className="flex flex-col">
            <span className="text-sm font-medium text-fg">{VISIBILITY[v].label}</span>
            <span className="text-meta text-muted">{VISIBILITY[v].sub}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

/** Who can see a project. The owner changes it; everyone else reads it. */
export function ShareDialog({
  open,
  onClose,
  project,
  teamId,
  userId,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  project: Project;
  teamId: string;
  userId: string;
  onChanged: () => void;
}) {
  const { data: members } = useMembers(teamId);
  const owner = project.owner_id === userId;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const people = new Set(project.project_people.map((p) => p.user_id));
  const nameOf = (id: string) =>
    members?.find((m) => m.user_id === id)?.profiles?.display_name ?? "Someone in the lab";
  const candidates = (members ?? []).filter(
    (m) =>
      m.user_id !== project.owner_id &&
      !people.has(m.user_id) &&
      (m.profiles?.display_name ?? "").toLowerCase().includes(query.trim().toLowerCase()),
  );

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t save that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} label="Who can see this project" className="max-w-[480px]">
      <div className="flex flex-col gap-4 p-6 pt-12">
        <h2 className="text-heading font-semibold">Who can see this project</h2>
        {!owner && (
          <p className="text-sm text-muted">Only the project’s owner can change this.</p>
        )}
        <VisibilityOptions
          value={project.visibility}
          disabled={!owner || busy}
          onChange={(v) => run(() => updateProject(project.id, { visibility: v }))}
        />
        {project.visibility === "people" && (
          <div className="flex flex-col gap-2">
            <ul className="flex flex-col gap-1">
              {project.owner_id && (
                <li className="flex items-center gap-2 text-sm">
                  <Avatar name={nameOf(project.owner_id)} size={22} />
                  <span className="flex-1">{project.owner_id === userId ? "You" : nameOf(project.owner_id)}</span>
                  <span className="text-meta text-faint">Owner</span>
                </li>
              )}
              {[...people].map((id) => (
                <li key={id} className="flex items-center gap-2 text-sm">
                  <Avatar name={nameOf(id)} size={22} />
                  <span className="flex-1">{id === userId ? "You" : nameOf(id)}</span>
                  {owner && (
                    <button
                      type="button"
                      disabled={busy}
                      aria-label={`Remove ${nameOf(id)}`}
                      onClick={() => run(() => setPerson(project.id, id, false))}
                      className="grid h-7 w-7 place-items-center rounded-control text-faint hover:bg-surface-2 hover:text-fg"
                    >
                      <X size={14} aria-hidden />
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {owner && (
              <div className="flex flex-col gap-1">
                <Label htmlFor="share-add">Add someone from the lab</Label>
                <Input
                  id="share-add"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Type a name"
                />
                {query.trim() && (
                  <ul className="flex max-h-40 flex-col overflow-auto rounded-control border border-border">
                    {candidates.length === 0 ? (
                      <li className="px-3 py-2 text-meta text-muted">Nobody in the lab by that name.</li>
                    ) : (
                      candidates.map((m) => (
                        <li key={m.user_id}>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => {
                              setQuery("");
                              void run(() => setPerson(project.id, m.user_id, true));
                            }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-2"
                          >
                            <Avatar name={m.profiles?.display_name ?? "?"} size={20} />
                            {m.profiles?.display_name ?? "Someone in the lab"}
                          </button>
                        </li>
                      ))
                    )}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => void navigator.clipboard?.writeText(window.location.href)}
          >
            Copy link
          </Button>
          <Button type="button" size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </Modal>
  );
}
