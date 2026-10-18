import { type ReactNode, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bell, BellOff, ChevronDown, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";

import { PaperPicker, type PickedPaper } from "@/components/PaperPicker";
import { usePaperModal } from "@/components/PaperModal";
import { useToast } from "@/components/Toast";
import { CollectionForm } from "@/components/trials/CollectionForm";
import { RequireTrials, TherapyList, TrialsDisclaimer } from "@/components/trials/parts";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useDismissable } from "@/hooks/useDismissable";
import { useMyRole } from "@/hooks/useMyRole";
import {
  type CollectionDetail,
  type CollectionFields,
  addCollectionPaper,
  addCollectionTrials,
  addNote,
  deleteCollection,
  deleteNote,
  fetchCollection,
  questionCaps,
  removeCollectionPaper,
  removeCollectionTrial,
  setFollowing,
  updateCollection,
} from "@/lib/collections";
import { supabase } from "@/lib/supabase";
import {
  type LabTrial,
  PATIENT_GROUPS,
  SETTINGS,
  THERAPY_CLASSES,
  fetchLabTrials,
  phaseLabel,
  statusLabel,
} from "@/lib/trials";
import { formatRelative, initials } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

export default function TrialCollection() {
  return (
    <RequireTrials>
      <CollectionPage />
    </RequireTrials>
  );
}

function CollectionPage() {
  const { id = "" } = useParams();
  const { team } = useAppContext();
  const detail = useQuery({ queryKey: ["collection", id], queryFn: () => fetchCollection(id) });
  const trials = useQuery({
    queryKey: ["lab-trials", team.id],
    queryFn: () => fetchLabTrials(team.id),
  });

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6 sm:p-8">
      <nav aria-label="Breadcrumb" className="text-sm text-muted">
        <Link to="/trials/collections" className="hover:text-fg">
          Collections
        </Link>
        {detail.data && <span className="text-faint"> / {detail.data.title}</span>}
      </nav>
      {(detail.isLoading || trials.isLoading) && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 size={14} className="animate-spin" aria-hidden /> Loading…
        </p>
      )}
      {detail.error && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load this collection. Try again.
        </p>
      )}
      {detail.data === null && (
        <p className="text-sm text-muted">
          This collection doesn’t exist any more.{" "}
          <Link to="/trials/collections" className="text-accent">
            Back to collections
          </Link>
        </p>
      )}
      {detail.data && trials.data && <Body c={detail.data} labTrials={trials.data} />}
      <TrialsDisclaimer />
    </div>
  );
}

function Body({ c, labTrials }: { c: CollectionDetail; labTrials: LabTrial[] }) {
  const { team, userId } = useAppContext();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const { data: role } = useMyRole(team.id, userId);
  const [editing, setEditing] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["collection", c.id] });
    qc.invalidateQueries({ queryKey: ["collections", team.id] });
  };

  const following = c.followers.includes(userId);
  const follow = useMutation({
    mutationFn: () => setFollowing(c.id, userId, !following),
    onSuccess: refresh,
    onError: () => toast({ message: "Couldn’t change that. Try again." }),
  });
  const save = useMutation({
    mutationFn: (f: CollectionFields) => updateCollection(c.id, userId, f),
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
  });
  const del = useMutation({
    mutationFn: () => deleteCollection(c.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collections", team.id] });
      toast({ message: `“${c.title}” deleted.` });
      navigate("/trials/collections");
    },
    onError: (e) => toast({ message: e instanceof Error ? e.message : "Couldn’t delete it." }),
  });
  const canDelete = c.created_by === userId || role === "owner";

  const members = new Map(labTrials.map((t) => [t.id, t]));
  const inCollection = c.trial_ids.map((id) => members.get(id)).filter(Boolean) as LabTrial[];

  const tags = [
    ...c.settings.map((s) => SETTINGS[s]),
    ...c.patient_groups.map((g) => PATIENT_GROUPS[g]),
    ...(c.comparison ? [c.comparison] : []),
  ];

  return (
    <>
      {editing ? (
        <section className="rounded-card border border-border bg-surface p-5">
          <CollectionForm
            initial={c}
            submitLabel="Save"
            pending={save.isPending}
            error={save.error ? "Couldn’t save. Try again." : null}
            onSubmit={(f) => save.mutate(f)}
            onCancel={() => setEditing(false)}
          />
        </section>
      ) : (
        <header className="flex flex-col gap-2">
          <div className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
            {questionCaps(c) || "Collection"}
          </div>
          <h1 className="text-display font-bold tracking-tight text-fg">{c.title}</h1>
          {c.question && <p className="max-w-[72ch] text-card text-fg">{c.question}</p>}
          {(tags.length > 0 || c.therapy_classes.length > 0) && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {tags.map((t) => (
                <span key={t} className="rounded-full border border-border px-2.5 py-0.5 text-muted">
                  {t}
                </span>
              ))}
              {c.therapy_classes.length > 0 && <TherapyList therapies={c.therapy_classes} />}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <p className="text-meta text-muted">
              {c.creator?.display_name ? `Created by ${c.creator.display_name} · ` : ""}
              {c.followers.length} following · updated {formatRelative(c.updated_at)}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="sm"
                aria-pressed={following}
                disabled={follow.isPending}
                onClick={() => follow.mutate()}
              >
                {following ? <BellOff size={14} aria-hidden /> : <Bell size={14} aria-hidden />}
                {following ? "Following" : "Follow"}
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
                <Pencil size={14} aria-hidden /> Edit
              </Button>
              {canDelete && (
                <Button
                  variant="danger"
                  size="sm"
                  disabled={del.isPending}
                  onClick={() => {
                    if (window.confirm(`Delete “${c.title}”? Its trials stay in All trials.`))
                      del.mutate();
                  }}
                >
                  <Trash2 size={14} aria-hidden /> Delete
                </Button>
              )}
            </div>
          </div>
        </header>
      )}

      <Section
        title={`Trials in this collection · ${inCollection.length}`}
        aside={<AddTrialMenu c={c} labTrials={labTrials} onAdded={refresh} />}
      >
        <TrialRows c={c} trials={inCollection} onChange={refresh} />
      </Section>

      <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
        <Section title="Lab notes">
          <Notes c={c} onChange={refresh} />
        </Section>
        <Section title="Papers">
          <Papers c={c} onChange={refresh} />
        </Section>
      </div>
    </>
  );
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-card border border-border bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-heading font-semibold text-fg">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

// --- trials --------------------------------------------------------------------

function TrialRows({
  c,
  trials,
  onChange,
}: {
  c: CollectionDetail;
  trials: LabTrial[];
  onChange: () => void;
}) {
  const { userId } = useAppContext();
  const remove = useMutation({
    mutationFn: (trialId: string) => removeCollectionTrial(c.id, trialId, userId),
    onSuccess: onChange,
  });
  if (trials.length === 0)
    return (
      <p className="text-sm text-muted">
        No trials yet. Add the trials that answer this question.
      </p>
    );
  return (
    <ul className="divide-y divide-border">
      {trials.map((t) => (
        <li key={t.id} className="flex flex-wrap items-start gap-x-6 gap-y-2 py-3">
          <div className="min-w-44">
            <Link
              to={`/trials/${t.nct_id}`}
              className="font-semibold text-fg hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {t.name}
            </Link>
            <div className="font-mono text-meta text-muted">
              {phaseLabel(t.phases)} · {t.nct_id}
            </div>
          </div>
          <div className="min-w-0 flex-1 text-sm text-fg">
            <TherapyList therapies={t.facts?.therapy_classes ?? []} />
            <div className="mt-1 text-meta text-muted">
              {[
                (t.facts?.settings ?? []).map((s) => SETTINGS[s]).join(", "),
                (t.facts?.patient_groups ?? []).map((g) => PATIENT_GROUPS[g]).join(", "),
                statusLabel(t.status),
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
          </div>
          <div className="flex items-center gap-3 text-meta text-muted">
            <span>
              {t.papers} {t.papers === 1 ? "paper" : "papers"}
            </span>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${t.name} from this collection`}
              disabled={remove.isPending}
              onClick={() => remove.mutate(t.id)}
            >
              <X size={15} aria-hidden />
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Lab trials not in the collection, the ones matching its question first. */
function AddTrialMenu({
  c,
  labTrials,
  onAdded,
}: {
  c: CollectionDetail;
  labTrials: LabTrial[];
  onAdded: () => void;
}) {
  const { userId } = useAppContext();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useDismissable(ref, open, (reason) => {
    setOpen(false);
    if (reason === "escape") button.current?.focus();
  });
  const add = useMutation({
    mutationFn: (trialId: string) => addCollectionTrials(c.id, [trialId], userId),
    onSuccess: () => {
      setOpen(false);
      onAdded();
    },
  });

  const overlaps = (a: string[], b: string[]) => !a.length || !b.length || a.some((x) => b.includes(x));
  const why = (t: LabTrial) => {
    const f = t.facts;
    const diff = [
      !overlaps(c.settings, f?.settings ?? []) && "setting",
      !overlaps(c.patient_groups, f?.patient_groups ?? []) && "patient group",
      !overlaps(
        c.therapy_classes.filter((x) => x !== "chemotherapy"),
        (f?.therapy_classes ?? []).filter((x) => x !== "chemotherapy"),
      ) && "therapy",
    ].filter(Boolean) as string[];
    return diff.length ? `Different ${diff.join(" and ")}` : "Matches";
  };
  const rest = labTrials.filter((t) => !c.trial_ids.includes(t.id));
  const same = rest.filter((t) => why(t) === "Matches");
  const other = rest.filter((t) => why(t) !== "Matches");

  const item = (t: LabTrial) => (
    <li key={t.id}>
      <button
        type="button"
        disabled={add.isPending}
        onClick={() => add.mutate(t.id)}
        className="flex w-full items-start justify-between gap-3 rounded-control px-2 py-2 text-left hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <span className="min-w-0">
          <span className="block text-sm font-medium text-fg">{t.name}</span>
          <span className="block truncate text-meta text-muted">
            {[
              (t.facts?.settings ?? []).map((s) => SETTINGS[s]).join("/"),
              (t.facts?.patient_groups ?? []).map((g) => PATIENT_GROUPS[g]).join(", "),
              (t.facts?.therapy_classes ?? []).map((x) => THERAPY_CLASSES[x]).join(" + "),
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </span>
        <span className="shrink-0 text-meta text-faint">{why(t)}</span>
      </button>
    </li>
  );

  return (
    <div ref={ref} className="relative">
      <Button
        ref={button}
        variant="secondary"
        size="sm"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <Plus size={14} aria-hidden /> Add trial <ChevronDown size={14} aria-hidden />
      </Button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1.5 max-h-96 w-80 overflow-y-auto rounded-card border border-border bg-surface p-2 shadow-lg">
          {same.length > 0 && (
            <>
              <div className="px-2 pb-1 pt-1 text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
                Same question
              </div>
              <ul>{same.map(item)}</ul>
            </>
          )}
          {other.length > 0 && (
            <>
              <div className="px-2 pb-1 pt-2 text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
                Other trials in Atlas
              </div>
              <ul>{other.map(item)}</ul>
            </>
          )}
          {rest.length === 0 && (
            <p className="px-2 py-2 text-sm text-muted">Every lab trial is already in here.</p>
          )}
          <Link
            to="/trials"
            className="mt-1 block border-t border-border px-2 pt-2 text-sm text-accent hover:underline"
          >
            Browse all trials →
          </Link>
        </div>
      )}
    </div>
  );
}

// --- notes ---------------------------------------------------------------------

function Notes({ c, onChange }: { c: CollectionDetail; onChange: () => void }) {
  const { userId } = useAppContext();
  const [body, setBody] = useState("");
  const add = useMutation({
    mutationFn: () => addNote(c.id, userId, body),
    onSuccess: () => {
      setBody("");
      onChange();
    },
  });
  const del = useMutation({ mutationFn: (id: string) => deleteNote(id), onSuccess: onChange });
  return (
    <div className="flex flex-col gap-3">
      {c.notes.length === 0 && (
        <p className="text-sm text-muted">
          What should the lab keep in mind when reading these trials together?
        </p>
      )}
      <ul className="flex flex-col gap-3">
        {c.notes.map((n) => {
          const name = n.author?.display_name ?? "Former member";
          return (
            <li key={n.id} className="flex gap-3">
              <span
                aria-hidden
                className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-surface-3 text-meta font-semibold text-fg"
              >
                {initials(name)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="whitespace-pre-wrap text-sm text-fg">{n.body}</p>
                <div className="mt-0.5 flex items-center gap-2 text-meta text-faint">
                  {name} · {formatRelative(n.created_at)}
                  {n.author_id === userId && (
                    <button
                      type="button"
                      onClick={() => del.mutate(n.id)}
                      className="text-muted hover:text-danger"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (body.trim() && !add.isPending) add.mutate();
        }}
      >
        <Textarea
          rows={2}
          maxLength={4000}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Add a note for the lab"
          aria-label="Add a note for the lab"
        />
        {add.error && (
          <p role="alert" className="text-sm text-danger">
            Couldn’t add the note. Try again.
          </p>
        )}
        <Button type="submit" size="sm" className="w-fit" disabled={!body.trim() || add.isPending}>
          Add note
        </Button>
      </form>
    </div>
  );
}

// --- papers --------------------------------------------------------------------

interface ReportingPaper {
  trial_id: string;
  papers: { id: string; title: string | null; venue: string | null; year: number | null } | null;
}

function Papers({ c, onChange }: { c: CollectionDetail; onChange: () => void }) {
  const { team, userId } = useAppContext();
  const { openPaper } = usePaperModal();
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<PickedPaper | null>(null);
  const reporting = useQuery({
    queryKey: ["collection-reporting", c.id, c.trial_ids],
    enabled: c.trial_ids.length > 0,
    queryFn: async (): Promise<ReportingPaper[]> => {
      const { data, error } = await supabase
        .from("paper_trials")
        .select("trial_id, papers(id, title, venue, year)")
        .eq("team_id", team.id)
        .in("trial_id", c.trial_ids)
        .in("status", ["auto", "confirmed"]);
      if (error) throw error;
      return data as unknown as ReportingPaper[];
    },
  });
  const add = useMutation({
    mutationFn: (paperId: string) => addCollectionPaper(c.id, paperId, userId),
    onSuccess: () => {
      setPicked(null);
      setPicking(false);
      onChange();
    },
  });
  const remove = useMutation({
    mutationFn: (paperId: string) => removeCollectionPaper(c.id, paperId, userId),
    onSuccess: onChange,
  });

  const about = c.papers.filter((p) => p.papers);
  // One row per paper, even if it reports two of the collection's trials.
  const byPaper = new Map<string, NonNullable<ReportingPaper["papers"]>>();
  for (const r of reporting.data ?? []) if (r.papers) byPaper.set(r.papers.id, r.papers);
  const reports = [...byPaper.values()];

  const row = (
    p: NonNullable<ReportingPaper["papers"]>,
    action?: ReactNode,
  ) => (
    <li key={p.id} className="flex items-start gap-2 py-2">
      <div className="min-w-0 flex-1">
        <button
          type="button"
          onClick={() => openPaper(p.id)}
          className="text-left text-sm font-medium text-fg hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {p.title ?? "Untitled paper"}
        </button>
        <div className="text-meta text-muted">{[p.venue, p.year].filter(Boolean).join(" · ")}</div>
      </div>
      {action}
    </li>
  );

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
          About the question
        </h3>
        {about.length === 0 ? (
          <p className="mt-1 text-sm text-muted">Meta-analyses and reviews that cover these trials.</p>
        ) : (
          <ul className="divide-y divide-border">
            {about.map((p) =>
              row(
                p.papers!,
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Remove from this collection"
                  onClick={() => remove.mutate(p.papers!.id)}
                >
                  <X size={14} aria-hidden />
                </Button>,
              ),
            )}
          </ul>
        )}
        {picking ? (
          <div className="mt-2 flex flex-col gap-2">
            <PaperPicker teamId={team.id} value={picked} onChange={setPicked} />
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={!picked || add.isPending}
                onClick={() => picked && add.mutate(picked.id)}
              >
                Add paper
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setPicking(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="ghost" size="sm" className="mt-1 w-fit" onClick={() => setPicking(true)}>
            <Plus size={14} aria-hidden /> Add paper to collection
          </Button>
        )}
      </div>
      <div>
        <h3 className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
          Reporting a trial in this collection
        </h3>
        {reports.length === 0 ? (
          <p className="mt-1 text-sm text-muted">
            No linked papers yet. Link them on each trial’s page.
          </p>
        ) : (
          <ul className="divide-y divide-border">{reports.map((p) => row(p))}</ul>
        )}
      </div>
    </div>
  );
}
