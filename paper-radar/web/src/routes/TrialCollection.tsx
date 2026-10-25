import { type ReactNode, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bell, BellOff, Check, ChevronDown, Loader2, Pencil, Plus, Sparkles, Trash2, X } from "lucide-react";

import { PaperPicker, type PickedPaper } from "@/components/PaperPicker";
import { usePaperModal } from "@/components/PaperModal";
import { useToast } from "@/components/Toast";
import { CollectionForm } from "@/components/trials/CollectionForm";
import { CompareView } from "@/components/trials/CompareView";
import { RequireTrials, TherapyList, TrialsDisclaimer } from "@/components/trials/parts";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Textarea } from "@/components/ui/textarea";
import { useDismissable } from "@/hooks/useDismissable";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useJustAdded } from "@/hooks/useJustAdded";
import { useMyRole } from "@/hooks/useMyRole";
import { useTrialCountries } from "@/hooks/useTrialCountries";
import {
  type CollectionDetail,
  type CollectionFields,
  type TrialExtraction,
  addCollectionPaper,
  addCollectionTrials,
  addNote,
  deleteCollection,
  deleteNote,
  fetchCollection,
  fetchExtractions,
  questionCaps,
  removeCollectionPaper,
  removeCollectionTrial,
  setFollowing,
  updateCollection,
} from "@/lib/collections";
import { ApiError, MAX_GET_DATA, getTrialsData } from "@/lib/api";
import { type CompareTrial, headline, verification } from "@/lib/compare";
import { EST_BATCH_USD, extractionState, inFlight } from "@/lib/extraction";
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
import { cn, formatRelative, initials } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";
import type { TrialFrom } from "@/routes/TrialPage";

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
  const detail = useQuery({
    queryKey: ["collection", team.id, id],
    queryFn: () => fetchCollection(id, team.id),
  });
  const trials = useQuery({
    queryKey: ["lab-trials", team.id],
    queryFn: () => fetchLabTrials(team.id),
  });
  useDocumentTitle(detail.data?.title ?? null);

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
          There’s no such collection in {team.name}.{" "}
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
  const [confirm, confirmDialog] = useConfirm();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["collection", team.id, c.id] });
    qc.invalidateQueries({ queryKey: ["collections", team.id] });
  };

  const following = c.followers.includes(userId);
  const follow = useMutation({
    mutationFn: () => setFollowing(c.id, userId, !following),
    onSuccess: refresh,
    onError: () => toast({ message: "Couldn’t change that. Try again." }),
  });
  const save = useMutation({
    mutationFn: (f: CollectionFields) => updateCollection(c.id, f),
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
    onError: (e) => toast({ message: e instanceof Error ? e.message : "Couldn’t delete the collection. Try again." }),
  });
  const canDelete = c.created_by === userId || role === "owner";

  const members = new Map(labTrials.map((t) => [t.id, t]));
  const inCollection = c.trial_ids.map((id) => members.get(id)).filter(Boolean) as LabTrial[];
  const extractions = useQuery({
    queryKey: ["collection-extractions", team.id, c.trial_ids],
    queryFn: () => fetchExtractions(team.id, c.trial_ids),
    // Adding a trial re-keys this: keep showing what we had meanwhile.
    placeholderData: (prev) => prev,
  });
  const comparable: CompareTrial[] = inCollection.flatMap((t) => {
    const e = extractions.data?.get(t.id);
    return e ? [{ id: t.id, name: t.name, extraction: e.extraction }] : [];
  });
  const [picked, setView] = useState<"overview" | "compare">("overview");
  const canCompare = comparable.length >= 2;
  // As with the papers: remove buttons only after "Edit", so a stray click
  // can't take a trial out.
  const [editingTrials, setEditingTrials] = useState(false);
  const countries = useTrialCountries(team.id);
  // Compare falls back to Overview when it stops being possible (a trial
  // removed), so the selected tab and what's on screen always agree.
  const view = canCompare ? picked : "overview";

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
            initial={{
              title: c.title,
              question: c.question,
              settings: c.settings,
              patient_groups: c.patient_groups,
              therapy_classes: c.therapy_classes,
              comparison: c.comparison,
            }}
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
                  onClick={async () => {
                    if (
                      await confirm({
                        title: `Delete “${c.title}”?`,
                        body: "Its notes go with it. Its trials stay in All trials, with their data.",
                        confirmLabel: "Delete collection",
                        danger: true,
                      })
                    )
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

      <ReadyBar c={c} trials={inCollection} extracted={extractions.data} loading={extractions.isLoading} />

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div
          role="tablist"
          aria-label="Collection views"
          className="flex gap-2"
          onKeyDown={(e) => {
            // Arrow keys move between tabs, as a tablist should.
            if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
            const next = view === "overview" && canCompare ? "compare" : "overview";
            setView(next);
            document.getElementById(`tab-${next}`)?.focus();
          }}
        >
          {(
            [
              ["overview", "Overview"],
              ["compare", `Compare trials${canCompare ? ` · ${comparable.length}` : ""}`],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              id={`tab-${key}`}
              type="button"
              role="tab"
              aria-selected={view === key}
              tabIndex={view === key ? 0 : -1}
              disabled={key === "compare" && !canCompare}
              aria-describedby={key === "compare" && !canCompare ? "compare-why" : undefined}
              onClick={() => setView(key)}
              className={cn(
                "min-h-10 rounded-control border px-4 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
                view === key
                  ? "border-border-strong bg-surface-2 text-fg"
                  : "border-border text-muted hover:text-fg",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {!canCompare && (
          <p id="compare-why" className="text-meta text-muted">
            {extractions.isLoading
              ? "Loading the trials’ data…"
              : `Compare needs two trials with data${comparable.length === 1 ? ": one has it so far" : ""}.`}
          </p>
        )}
      </div>

      {view === "compare" && canCompare ? (
        <CompareView available={comparable} countries={countries.data} />
      ) : (
        <Section
          title={`Trials in this collection · ${inCollection.length}`}
          aside={
            <div className="flex items-center gap-3">
              {inCollection.length > 0 && (
                <EditToggle
                  on={editingTrials}
                  onToggle={() => setEditingTrials((e) => !e)}
                  label="Edit the trials"
                />
              )}
              <AddTrialMenu
                c={c}
                labTrials={labTrials}
                onAdded={() => {
                  setEditingTrials(false);
                  refresh();
                }}
              />
            </div>
          }
        >
          {extractions.error && (
            <p role="alert" className="text-sm text-danger">
              Couldn’t load the trials’ extracted data. Try again.
            </p>
          )}
          <TrialRows
            c={c}
            trials={inCollection}
            extractions={extractions.data}
            loading={extractions.isLoading}
            onChange={refresh}
            editing={editingTrials}
          />
        </Section>
      )}

      {/* minmax(0,…): a long title can't widen its column and squeeze the other. */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <Section title="Lab notes">
          <Notes c={c} onChange={refresh} />
        </Section>
        <Section title="Papers">
          <Papers c={c} onChange={refresh} />
        </Section>
      </div>
      {confirmDialog}
    </>
  );
}

/** "Edit" / "Done": shows a list's remove buttons. A button like the ones
 *  beside it (Add trial), not a bare link. */
function EditToggle({ on, onToggle, label }: { on: boolean; onToggle: () => void; label: string }) {
  return (
    <Button
      variant={on ? "secondary" : "ghost"}
      size="sm"
      aria-pressed={on}
      aria-label={on ? "Done editing" : label}
      onClick={onToggle}
    >
      {on ? <Check size={14} aria-hidden /> : <Pencil size={14} aria-hidden />}
      {on ? "Done" : "Edit"}
    </Button>
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
  extractions,
  loading,
  onChange,
  editing,
}: {
  c: CollectionDetail;
  trials: LabTrial[];
  extractions?: Map<string, TrialExtraction>;
  /** Extracted data is still loading: don't claim it's missing. */
  loading: boolean;
  onChange: () => void;
  /** Show each row's remove button. */
  editing: boolean;
}) {
  const toast = useToast();
  const { userId } = useAppContext();
  const from: TrialFrom = { from: { to: `/trials/collections/${c.id}`, label: c.title } };
  const remove = useMutation({
    mutationFn: (t: LabTrial) => removeCollectionTrial(c.id, t.id),
    onSuccess: (_r, t) => {
      onChange();
      // One click took it out, so one click puts it back.
      toast({
        message: `${t.name} taken out of this collection.`,
        actionLabel: "Undo",
        // Back in, credited to whoever undid it: the database lets people add
        // only as themselves, and nothing shows who added a trial or when.
        onAction: async () => {
          await addCollectionTrials(c.id, [t.id], userId);
          onChange();
        },
      });
    },
    onError: () => toast({ message: "Couldn’t remove that trial. Try again." }),
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
              state={from}
              className="font-semibold text-fg hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {t.name}
            </Link>
            <div className="font-mono text-meta text-muted">
              {phaseLabel(t.phases)} · {t.nct_id}
            </div>
          </div>
          <div className="min-w-0 flex-1 basis-56 text-sm text-fg">
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
          <div className="min-w-40 text-sm">
            {(() => {
              const e = extractions?.get(t.id);
              if (!e && (loading || !extractions)) return <span className="text-meta text-faint">…</span>;
              if (!e)
                return (
                  <Link to={`/trials/${t.nct_id}`} state={from} className="text-meta text-muted hover:text-accent">
                    {dataState(t)}
                  </Link>
                );
              const status = verification(e.extraction, e.reviewed);
              return (
                <>
                  <div className="font-mono text-fg">{headline(e.extraction) || "–"}</div>
                  <span
                    className={cn(
                      "mt-0.5 inline-block rounded-full px-2 text-[11px]",
                      status === "Verified"
                        ? "border border-accent/50 text-accent"
                        : "border border-dashed border-border-strong text-muted",
                    )}
                  >
                    {status}
                  </span>
                </>
              );
            })()}
          </div>
          <div className="ml-auto flex items-center gap-3 text-meta text-muted">
            <span>
              {t.papers} {t.papers === 1 ? "paper" : "papers"}
            </span>
            {editing && (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove ${t.name} from this collection`}
                title="Remove from this collection"
                disabled={remove.isPending}
                onClick={() => remove.mutate(t)}
              >
                <X size={15} aria-hidden />
              </Button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Where a trial without data stands, in a few words. */
function dataState(t: LabTrial): string {
  switch (extractionState(t.facts)) {
    case "queued":
      return "Queued for data";
    case "batched":
      return "Processing (a few hours)";
    case "running":
      return "Claude is reading it";
    case "stalled":
      return "Extraction stopped: open to restart";
    case "failed":
      return "Extraction failed: open to retry";
    default:
      return "No data yet";
  }
}

type Outcome = {
  queued: LabTrial[];
  needPdf: LabTrial[];
  /** Only suggested papers: one to confirm before Atlas can fetch it. */
  unconfirmed: LabTrial[];
  stopped: string | null;
};

/** How many of the collection's trials have data, and one action to get the
 *  rest: the server fetches each one's open-access full text, then queues it
 *  for the half-price batch. Trials with no open-access text are listed: they
 *  need a PDF uploaded on their page. */
function ReadyBar({
  c,
  trials,
  extracted,
  loading,
}: {
  c: CollectionDetail;
  trials: LabTrial[];
  extracted?: Map<string, TrialExtraction>;
  loading: boolean;
}) {
  const { team, userId } = useAppContext();
  const qc = useQueryClient();
  // The cost estimate is for owners, like every amount (members aren't asked
  // to weigh the lab's spend).
  const { data: role } = useMyRole(team.id, userId);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const from: TrialFrom = { from: { to: `/trials/collections/${c.id}`, label: c.title } };
  // Data on record counts even before its values load: a failed load must
  // never offer to re-extract (that costs money and wipes the lab's checks).
  const missing = trials.filter((t) => !t.facts?.extracted_at && !extracted?.has(t.id));
  const waiting = missing.filter((t) => inFlight(extractionState(t.facts)));
  const todo = missing.filter((t) => !waiting.includes(t));

  const run = useMutation({
    mutationFn: async (): Promise<Outcome> => {
      const out: Outcome = { queued: [], needPdf: [], unconfirmed: [], stopped: null };
      const byId = new Map(todo.map((t) => [t.id, t]));
      const pick = (ids: string[]) => ids.flatMap((id) => byId.get(id) ?? []);
      for (let i = 0; i < todo.length; i += MAX_GET_DATA) {
        try {
          const r = await getTrialsData(team.id, todo.slice(i, i + MAX_GET_DATA).map((t) => t.id));
          // Skipped: queued or running meanwhile, which is what we wanted.
          out.queued.push(...pick([...r.queued, ...r.skipped]));
          out.needPdf.push(...pick(r.need_pdf));
          out.unconfirmed.push(...pick(r.unconfirmed ?? []));
        } catch (e) {
          // The lab's monthly cap (402) or the hourly limit (429) ends the run.
          out.stopped = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
          break;
        }
      }
      return out;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["lab-trials", team.id] });
      qc.invalidateQueries({ queryKey: ["extraction-budget", team.id] });
    },
    onSuccess: setOutcome,
  });

  if (loading || trials.length === 0) return null;
  const have = trials.length - missing.length;
  if (missing.length === 0 && !outcome) return null;
  const links = (ts: LabTrial[]) =>
    ts.map((t, i) => (
      <span key={t.id}>
        {i > 0 && ", "}
        <Link to={`/trials/${t.nct_id}`} state={from} className="text-accent hover:underline">
          {t.name}
        </Link>
      </span>
    ));

  return (
    <section
      aria-label="Trial data"
      className="flex flex-col gap-2 rounded-card border border-accent/40 bg-accent-weak/40 p-4"
    >
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 basis-72">
          <div className="font-semibold text-fg">
            {have} of {trials.length} {trials.length === 1 ? "trial has" : "trials have"} data
          </div>
          <p className="text-sm text-muted">
            {todo.length > 0
              ? `Get data for the other ${todo.length === 1 ? "one" : todo.length}${role === "owner" ? `: about $${(todo.length * EST_BATCH_USD).toFixed(2)},` : ","} ready in a few hours.`
              : waiting.length > 0
                ? `${waiting.length === 1 ? "The other one is" : `The other ${waiting.length} are`} on the way: usually ready within a few hours.`
                : "Every trial has data."}
            {todo.length > 0 && waiting.length > 0 && ` ${waiting.length} more on the way.`}
          </p>
        </div>
        {todo.length > 0 && (
          <Button disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? (
              <Loader2 size={16} className="animate-spin" aria-hidden />
            ) : (
              <Sparkles size={16} aria-hidden />
            )}
            {run.isPending ? "Queuing…" : `Queue data for ${todo.length === 1 ? "it" : todo.length}`}
          </Button>
        )}
      </div>
      {outcome && (
        <p className="text-sm text-fg" aria-live="polite">
          {outcome.queued.length > 0 && <>Queued: {links(outcome.queued)}. </>}
          {outcome.needPdf.length > 0 && (
            <>
              No free full text for {links(outcome.needPdf)}: upload the paper’s PDF on its page.{" "}
            </>
          )}
          {outcome.unconfirmed.length > 0 && (
            <>
              Only suggested papers for {links(outcome.unconfirmed)}: confirm the right one on its
              page, then get data again.{" "}
            </>
          )}
          {outcome.stopped && <span className="text-danger">Stopped: {outcome.stopped}</span>}
        </p>
      )}
    </section>
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
  const toast = useToast();
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
    onError: () => {
      setOpen(false);
      toast({ message: "Couldn’t add that trial. It may have left the lab’s list." });
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
  const { team, userId } = useAppContext();
  const { data: role } = useMyRole(team.id, userId);
  const toast = useToast();
  const [body, setBody] = useState("");
  const add = useMutation({
    mutationFn: () => addNote(c.id, userId, body),
    onSuccess: () => {
      setBody("");
      onChange();
    },
  });
  const del = useMutation({
    mutationFn: (id: string) => deleteNote(id),
    onSuccess: onChange,
    onError: () => toast({ message: "Couldn’t delete the note. Try again." }),
  });
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
                  {/* Yours; or, for a lab owner, notes whose author left Atlas. */}
                  {(n.author_id === userId || (n.author_id === null && role === "owner")) && (
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
        <Button
          type="submit"
          size="sm"
          // Secondary while empty: a disabled primary reads as washed-out teal.
          variant={body.trim() ? "default" : "secondary"}
          className="w-fit"
          disabled={!body.trim() || add.isPending}
        >
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
  // Remove buttons show only while editing: a × beside every title was easy
  // to hit by accident.
  const [editingList, setEditingList] = useState(false);
  const { justAdded, markAdded, rowRef } = useJustAdded();
  const [addedTitle, setAddedTitle] = useState("");
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
  const toast = useToast();
  const add = useMutation({
    mutationFn: (p: PickedPaper) => addCollectionPaper(c.id, p.id, userId),
    // The search closes, and the new paper shows where it landed (the end of
    // the list, next to the button that added it), marked "Added".
    onSuccess: (_r, p) => {
      setPicking(false);
      // Back to reading: an add isn't an edit, and stale crosses are a trap.
      setEditingList(false);
      setAddedTitle(p.title);
      markAdded(p.id);
      onChange();
    },
    onError: () => toast({ message: "Couldn’t add that paper. Try again." }),
  });
  const remove = useMutation({
    mutationFn: (p: { id: string; title: string }) => removeCollectionPaper(c.id, p.id),
    onSuccess: (_r, p) => {
      onChange();
      toast({
        message: `“${p.title}” taken out of this collection.`,
        actionLabel: "Undo",
        onAction: async () => {
          await addCollectionPaper(c.id, p.id, userId);
          onChange();
        },
      });
    },
    onError: () => toast({ message: "Couldn’t remove that paper. Try again." }),
  });
  // Papers the lab still holds. One the lab has since removed (or that the
  // viewer can't read) stays listed as removed, so someone can take it out.
  const held = useQuery({
    queryKey: ["collection-held", team.id, c.id, c.papers.map((p) => p.paper_id)],
    enabled: c.papers.length > 0,
    queryFn: async (): Promise<Set<string>> => {
      const { data, error } = await supabase
        .from("paper_posts")
        .select("paper_id")
        .eq("team_id", team.id)
        .in("paper_id", c.papers.map((p) => p.paper_id));
      if (error) throw error;
      return new Set((data as { paper_id: string }[]).map((r) => r.paper_id));
    },
  });

  // Oldest first, so a new paper always lands at the end, by the Add button.
  const about = [...c.papers].sort((a, b) => a.added_at.localeCompare(b.added_at));
  // One row per paper, even if it reports two of the collection's trials.
  const byPaper = new Map<string, NonNullable<ReportingPaper["papers"]>>();
  for (const r of reporting.data ?? []) if (r.papers) byPaper.set(r.papers.id, r.papers);
  const reports = [...byPaper.values()];

  const row = (
    p: NonNullable<ReportingPaper["papers"]>,
    action?: ReactNode,
    isNew = false,
  ) => (
    <li
      key={p.id}
      ref={isNew ? rowRef(p.id) : undefined}
      className={cn(
        "flex items-start gap-2 py-2 transition-colors duration-700",
        isNew && "-mx-2 rounded-control bg-accent-weak px-2",
      )}
    >
      <div className="min-w-0 flex-1">
        {isNew && (
          <span className="mb-0.5 inline-flex items-center gap-1 text-meta font-semibold text-accent">
            <Check size={12} aria-hidden /> Added
          </span>
        )}
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
        <div className="flex min-h-8 items-center justify-between gap-2">
          <h3 className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
            Relevant
          </h3>
          {about.length > 0 && (
            <EditToggle
              on={editingList}
              onToggle={() => setEditingList((e) => !e)}
              label="Edit the relevant papers"
            />
          )}
        </div>
        <p className="sr-only" aria-live="polite">
          {justAdded ? `Added ${addedTitle} to the collection.` : ""}
        </p>
        {about.length === 0 ? (
          <p className="mt-1 text-sm text-muted">
            Reviews, meta-analyses and other papers the lab reads alongside these trials.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {about.map((p) => {
              const action = editingList && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove ${p.papers?.title ?? "this paper"} from this collection`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate({ id: p.paper_id, title: p.papers?.title ?? "Untitled paper" })}
                >
                  <X size={14} aria-hidden />
                </Button>
              );
              return p.papers && (!held.data || held.data.has(p.paper_id)) ? (
                row(p.papers, action, p.paper_id === justAdded)
              ) : (
                <li key={p.paper_id} className="flex items-center gap-2 py-2">
                  <span className="flex-1 text-sm text-faint">
                    A paper no longer in {team.name}’s library
                  </span>
                  {action}
                </li>
              );
            })}
          </ul>
        )}
        {picking ? (
          <div className="mt-2 flex flex-col gap-2">
            {/* One click on a result adds it: no second "Add" step. */}
            <PaperPicker
              teamId={team.id}
              value={null}
              onChange={(p) => p && add.mutate(p)}
              exclude={[...c.papers.map((p) => p.paper_id), ...reports.map((p) => p.id)]}
              busy={add.isPending}
              autoFocus
            />
            <Button size="sm" variant="ghost" className="w-fit" onClick={() => setPicking(false)}>
              Cancel
            </Button>
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
