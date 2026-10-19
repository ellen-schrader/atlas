import { type ReactNode, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { FlaskConical, LayoutGrid, List, Loader2, Plus, Search, X } from "lucide-react";

import { AddTrialDialog } from "@/components/trials/AddTrialDialog";
import { EMPTY_COLLECTION, NewCollectionDialog } from "@/components/trials/CollectionForm";
import {
  FilterMenu,
  type FilterOption,
  RequireTrials,
  TherapyList,
  TherapySwatch,
  TrialsDisclaimer,
  Unclassified,
} from "@/components/trials/parts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { type Collection, fetchCollections, sameSettingAndGroup, sharedTags } from "@/lib/collections";
import { extractionRunning } from "@/lib/extraction";
import {
  type LabTrial,
  PATIENT_GROUPS,
  SETTINGS,
  THERAPY_CLASSES,
  type TherapyClass,
  classification,
  fetchLabTrials,
  phaseLabel,
  statusLabel,
} from "@/lib/trials";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

type FilterKey = "therapy" | "group" | "setting" | "phase";
type Sort = "papers" | "name" | "added";

const MENUS: { key: FilterKey; label: string }[] = [
  { key: "therapy", label: "Therapy" },
  { key: "group", label: "Patient group" },
  { key: "setting", label: "Setting" },
  { key: "phase", label: "Phase" },
];

function valuesOf(t: LabTrial, key: FilterKey): string[] {
  if (key === "phase") return [phaseLabel(t.phases)];
  const f = t.facts;
  if (!f) return [];
  return key === "therapy" ? f.therapy_classes : key === "group" ? f.patient_groups : f.settings;
}

function labelOf(key: FilterKey, value: string): string {
  const maps: Record<string, Record<string, string>> = {
    therapy: THERAPY_CLASSES,
    group: PATIENT_GROUPS,
    setting: SETTINGS,
  };
  return maps[key]?.[value] ?? value;
}

const list = (t: LabTrial, key: "settings" | "patient_groups", labels: Record<string, string>) =>
  (t.facts?.[key] ?? []).map((v) => labels[v]).join(", ") || "—";

/** Whether Claude has the trial's data yet: what Compare needs. */
function DataState({ t }: { t: LabTrial }) {
  const f = t.facts;
  if (f?.extracted_at) return <span className="text-fg">Extracted</span>;
  const s = f?.extraction_status;
  if (s === "queued" || s === "batched" || extractionRunning(s ?? null, f?.extraction_started_at ?? null))
    return <span className="text-muted">On the way</span>;
  return <span className="text-faint">{s === "failed" ? "Failed" : "Not yet"}</span>;
}

/** The lab's collections each trial is in. */
type InCollections = Map<string, Collection[]>;

function CollectionNames({ t, inCollections }: { t: LabTrial; inCollections: InCollections }) {
  const cs = inCollections.get(t.id) ?? [];
  if (cs.length === 0) return <span className="text-faint">—</span>;
  return (
    <span className="flex flex-col gap-0.5">
      {cs.map((c) => (
        <Link key={c.id} to={`/trials/collections/${c.id}`} className="relative z-10 truncate text-fg hover:text-accent">
          {c.title}
        </Link>
      ))}
    </span>
  );
}

export default function Trials() {
  return (
    <RequireTrials>
      <AllTrials />
    </RequireTrials>
  );
}

function AllTrials() {
  const { team } = useAppContext();
  const [params, setParams] = useSearchParams();
  const [adding, setAdding] = useState(false);
  // Trials picked for a new collection (the mock-up's tray).
  const [picked, setPicked] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const pick = (id: string) =>
    setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  const collections = useQuery({
    queryKey: ["collections", team.id],
    queryFn: () => fetchCollections(team.id),
  });
  const inCollections: InCollections = new Map();
  for (const c of collections.data ?? [])
    for (const id of c.trial_ids) inCollections.set(id, [...(inCollections.get(id) ?? []), c]);
  const { data: trials, isLoading, error } = useQuery({
    queryKey: ["lab-trials", team.id],
    queryFn: () => fetchLabTrials(team.id),
    // Claude classifies new trials in the background: look again shortly.
    refetchInterval: (q) =>
      q.state.data?.some((t) => classification(t.facts, t.added_at) === "pending") ? 5000 : false,
  });

  const selected = (key: FilterKey) => params.get(key)?.split(",").filter(Boolean) ?? [];
  const view = params.get("view") === "grid" ? "grid" : "list";
  const sort = (params.get("sort") as Sort) || "papers";
  const q = params.get("q") ?? "";
  const needle = q.trim().toLowerCase();
  const set = (key: string, value: string | null) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  const toggle = (key: FilterKey, value: string) => {
    const cur = selected(key);
    set(key, (cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value]).join(","));
  };
  const clearAll = () => setParams((p) => {
    const next = new URLSearchParams(p);
    for (const m of MENUS) next.delete(m.key);
    next.delete("q");
    return next;
  }, { replace: true });

  const all = trials ?? [];
  const matches = (t: LabTrial, skip: FilterKey | null) =>
    (!needle || `${t.name} ${t.nct_id} ${t.title ?? ""} ${t.sponsor ?? ""}`.toLowerCase().includes(needle)) &&
    MENUS.every(({ key }) => {
      if (key === skip) return true;
      const sel = selected(key);
      return sel.length === 0 || sel.some((s) => valuesOf(t, key).includes(s));
    });

  const shown = useMemo(() => {
    const out = all.filter((t) => matches(t, null));
    const byName = (a: LabTrial, b: LabTrial) => a.name.localeCompare(b.name);
    out.sort(
      sort === "name"
        ? byName
        : sort === "added"
          ? (a, b) => b.added_at.localeCompare(a.added_at)
          : (a, b) => b.papers - a.papers || byName(a, b),
    );
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, params]);

  const phaseValues = [...new Set(all.map((t) => phaseLabel(t.phases)))].sort();
  const optionsFor = (key: FilterKey): FilterOption[] => {
    const values =
      key === "therapy"
        ? Object.keys(THERAPY_CLASSES)
        : key === "group"
          ? Object.keys(PATIENT_GROUPS)
          : key === "setting"
            ? Object.keys(SETTINGS)
            : phaseValues;
    return values.map((v) => ({
      value: v,
      label: labelOf(key, v),
      count: all.filter((t) => matches(t, key) && valuesOf(t, key).includes(v)).length,
      swatch: key === "therapy" ? (v as TherapyClass) : undefined,
    }));
  };
  const active = MENUS.flatMap(({ key }) => selected(key).map((v) => ({ key, v })));

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6 sm:p-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-display font-bold tracking-tight text-fg">All trials</h1>
          <p className="mt-1.5 max-w-[64ch] text-sm text-muted">
            The breast cancer trials {team.name} follows. Atlas adds the ones your papers name and
            links the papers that report them.
          </p>
        </div>
        <Button onClick={() => setAdding(true)}>
          <Plus size={16} aria-hidden /> Add trial
        </Button>
      </header>

      {isLoading && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 size={14} className="animate-spin" aria-hidden /> Loading trials…
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load the lab’s trials. Try again.
        </p>
      )}

      {trials && trials.length === 0 && (
        <div className="flex flex-col items-start gap-3 rounded-card border border-dashed border-border-strong p-6">
          <FlaskConical size={20} className="text-muted" aria-hidden />
          <p className="max-w-[60ch] text-sm text-muted">
            No trials yet. Add one by NCT ID or name. Papers you share that name a trial’s NCT ID
            in their abstract add it here by themselves.
          </p>
          <Button variant="secondary" onClick={() => setAdding(true)}>
            <Plus size={16} aria-hidden /> Add trial
          </Button>
        </div>
      )}

      {trials && trials.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative min-w-56 flex-1 sm:max-w-xs">
              <span className="sr-only">Search trials</span>
              <Search
                size={15}
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
              />
              <Input
                value={q}
                onChange={(e) => set("q", e.target.value || null)}
                placeholder="Name, NCT ID, sponsor or words"
                className="pl-9"
              />
            </label>
            {MENUS.map((m) => (
              <FilterMenu
                key={m.key}
                label={m.label}
                options={optionsFor(m.key)}
                selected={selected(m.key)}
                onToggle={(v) => toggle(m.key, v)}
              />
            ))}
            <div className="ml-auto flex items-center gap-2">
              <label className="flex items-center gap-2 text-sm text-muted">
                Sort
                <select
                  value={sort}
                  onChange={(e) => set("sort", e.target.value === "papers" ? null : e.target.value)}
                  className="h-10 rounded-control border border-border bg-surface px-2 text-sm text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  <option value="papers">Most papers</option>
                  <option value="name">Name</option>
                  <option value="added">Recently added</option>
                </select>
              </label>
              <div className="flex overflow-hidden rounded-control border border-border">
                {(["list", "grid"] as const).map((v) => {
                  const Icon = v === "list" ? List : LayoutGrid;
                  return (
                    <button
                      key={v}
                      type="button"
                      aria-pressed={view === v}
                      aria-label={v === "list" ? "List view" : "Grid view"}
                      onClick={() => set("view", v === "list" ? null : v)}
                      className={cn(
                        "grid h-10 w-11 place-items-center transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent",
                        view === v ? "bg-surface-2 text-fg" : "bg-surface text-muted hover:text-fg",
                      )}
                    >
                      <Icon size={16} aria-hidden />
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="flex min-h-7 flex-wrap items-center gap-2 text-sm">
            <span className="text-muted" aria-live="polite">
              {shown.length} {shown.length === 1 ? "trial" : "trials"}
              {shown.length !== all.length && ` (of ${all.length})`}
            </span>
            {active.map(({ key, v }) => (
              <button
                key={`${key}:${v}`}
                type="button"
                onClick={() => toggle(key, v)}
                aria-label={`Remove filter ${labelOf(key, v)}`}
                className="inline-flex items-center gap-1 rounded-full border border-accent/40 bg-accent-weak px-2.5 py-0.5 text-meta text-fg hover:border-accent"
              >
                {labelOf(key, v)} <X size={12} aria-hidden />
              </button>
            ))}
            {(active.length > 0 || needle) && (
              <button
                type="button"
                onClick={clearAll}
                className="text-meta font-medium text-accent hover:underline"
              >
                Clear all
              </button>
            )}
            {picked.length === 0 && (
              <span className="ml-auto hidden text-meta text-faint sm:inline">
                Tick trials to save them as a collection
              </span>
            )}
          </div>

          {shown.length === 0 ? (
            <div className="flex flex-col items-start gap-2 rounded-card border border-dashed border-border-strong p-6 text-sm text-muted">
              No trials match these filters.
              <Button variant="secondary" size="sm" onClick={clearAll}>
                Clear filters
              </Button>
            </div>
          ) : view === "list" ? (
            <>
              {/* A six-column table doesn't fit a phone: cards there. */}
              <div className="hidden sm:block">
                <TrialTable trials={shown} picked={picked} onPick={pick} inCollections={inCollections} />
              </div>
              <div className="sm:hidden">
                <TrialGrid trials={shown} picked={picked} onPick={pick} inCollections={inCollections} />
              </div>
            </>
          ) : (
            <TrialGrid trials={shown} picked={picked} onPick={pick} inCollections={inCollections} />
          )}
        </>
      )}

      <TrialsDisclaimer />
      <AddTrialDialog open={adding} onClose={() => setAdding(false)} teamId={team.id} />
      <PickTray
        trials={picked.map((id) => all.find((t) => t.id === id)).filter(Boolean) as LabTrial[]}
        onRemove={pick}
        onClear={() => setPicked([])}
        onSave={() => setSaving(true)}
      />
      <NewCollectionDialog
        open={saving}
        onClose={() => setSaving(false)}
        teamId={team.id}
        trialIds={picked}
        initial={{ ...EMPTY_COLLECTION, ...sharedTags(all.filter((t) => picked.includes(t.id))) }}
        note={`With ${all
          .filter((t) => picked.includes(t.id))
          .map((t) => t.name)
          .join(", ")}.`}
      />
    </div>
  );
}

/** `content` once Claude (or a person) has classified the trial; until then,
 *  whether it's on its way or didn't happen. */
function Classified({ t, children }: { t: LabTrial; children: ReactNode }) {
  const state = classification(t.facts, t.added_at);
  return state === "done" ? <>{children}</> : <Unclassified state={state} />;
}

function PaperCount({ t }: { t: LabTrial }) {
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span className="font-mono">{t.papers}</span>
      {t.suggestions > 0 && (
        <span
          className="rounded-full border border-border-strong px-1.5 text-meta text-muted"
          title={`${t.suggestions} suggested ${t.suggestions === 1 ? "paper" : "papers"} to review`}
        >
          +{t.suggestions} to review
        </span>
      )}
    </span>
  );
}

interface Pickable {
  picked: string[];
  onPick: (id: string) => void;
  inCollections: InCollections;
}

function PickBox({ t, picked, onPick }: { t: LabTrial } & Omit<Pickable, "inCollections">) {
  const on = picked.includes(t.id);
  return (
    <input
      type="checkbox"
      checked={on}
      onChange={() => onPick(t.id)}
      aria-label={`Select ${t.name} for a collection`}
      className="h-4 w-4 accent-[var(--accent)]"
    />
  );
}

function TrialTable({ trials, picked, onPick, inCollections }: { trials: LabTrial[] } & Pickable) {
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-surface">
      <table className="w-full min-w-[860px] text-left text-sm">
        <thead className="border-b border-border text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
          <tr>
            <th className="w-10 py-3 pl-4">
              <span className="sr-only">Select for a collection</span>
            </th>
            <th className="px-3 py-3 font-semibold">Trial</th>
            <th className="px-3 py-3 font-semibold">Setting</th>
            <th className="px-3 py-3 font-semibold">Therapy</th>
            <th className="px-3 py-3 font-semibold">Patient group</th>
            <th className="px-3 py-3 font-semibold">Data</th>
            <th className="px-3 py-3 font-semibold">Collections</th>
            <th className="px-4 py-3 font-semibold">Papers</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {trials.map((t) => (
            <tr key={t.id} className="align-top transition hover:bg-surface-2/60">
              <td className="py-3.5 pl-4">
                <PickBox t={t} picked={picked} onPick={onPick} />
              </td>
              <td className="px-3 py-3">
                <Link
                  to={`/trials/${t.nct_id}`}
                  className="font-semibold text-fg hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  {t.name}
                </Link>
                <div className="font-mono text-meta text-muted">
                  {phaseLabel(t.phases)} · {t.nct_id}
                </div>
                <div className="text-meta text-muted">{statusLabel(t.status)}</div>
              </td>
              <td className="px-3 py-3 text-fg">
                <Classified t={t}>{list(t, "settings", SETTINGS)}</Classified>
              </td>
              <td className="px-3 py-3 text-fg">
                <Classified t={t}>
                  <TherapyList therapies={t.facts?.therapy_classes ?? []} />
                </Classified>
              </td>
              <td className="px-3 py-3 text-fg">
                <Classified t={t}>{list(t, "patient_groups", PATIENT_GROUPS)}</Classified>
              </td>
              <td className="px-3 py-3">
                <DataState t={t} />
              </td>
              <td className="max-w-48 px-3 py-3">
                <CollectionNames t={t} inCollections={inCollections} />
              </td>
              <td className="px-4 py-3 text-fg">
                <PaperCount t={t} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TrialGrid({ trials, picked, onPick, inCollections }: { trials: LabTrial[] } & Pickable) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {trials.map((t) => {
        const therapies = t.facts?.therapy_classes ?? [];
        return (
          // The title's link stretches over the card (after:inset-0); the
          // checkbox sits above it, so ticking doesn't open the trial.
          <div
            key={t.id}
            className="relative flex flex-col gap-2 overflow-hidden rounded-card border border-border bg-surface p-4 pl-5 transition focus-within:ring-2 focus-within:ring-accent hover:border-border-strong"
          >
            {/* The leading therapy's colour, as the mock-up's card edge. */}
            {therapies[0] && (
              <span aria-hidden className="absolute inset-y-0 left-0 w-[3px]">
                <TherapySwatch therapy={therapies[0]} className="h-full w-full rounded-none" />
              </span>
            )}
            <div className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
              <Classified t={t}>{list(t, "settings", SETTINGS)}</Classified> ·{" "}
              {phaseLabel(t.phases)}
            </div>
            <div className="flex items-start justify-between gap-2">
              <Link
                to={`/trials/${t.nct_id}`}
                className="text-card font-semibold text-fg after:absolute after:inset-0 focus-visible:outline-none"
              >
                {t.name}
              </Link>
              <span className="relative z-10 -m-2 p-2">
                <PickBox t={t} picked={picked} onPick={onPick} />
              </span>
            </div>
            <p className="line-clamp-2 text-sm text-muted">{t.title}</p>
            <div className="text-sm text-fg">
              <Classified t={t}>
                <TherapyList therapies={therapies} />
              </Classified>
            </div>
            <div className="text-meta text-muted">
              Data: <DataState t={t} />
              {(inCollections.get(t.id)?.length ?? 0) > 0 &&
                ` · in ${inCollections.get(t.id)!.map((c) => c.title).join(", ")}`}
            </div>
            <div className="mt-auto flex items-center justify-between pt-2 text-meta text-muted">
              <span>
                <Classified t={t}>{list(t, "patient_groups", PATIENT_GROUPS)}</Classified>
              </span>
              <PaperCount t={t} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PickTray({
  trials,
  onRemove,
  onClear,
  onSave,
}: {
  trials: LabTrial[];
  onRemove: (id: string) => void;
  onClear: () => void;
  onSave: () => void;
}) {
  if (trials.length === 0) return null;
  const mixed = !sameSettingAndGroup(trials);
  return (
    <div
      role="region"
      aria-label="Selected trials"
      className="sticky bottom-4 z-20 flex flex-wrap items-center gap-3 rounded-card border border-border-strong bg-surface p-3 shadow-lg"
    >
      <ul className="flex flex-1 flex-wrap gap-1.5">
        {trials.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              onClick={() => onRemove(t.id)}
              aria-label={`Remove ${t.name}`}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-meta text-fg hover:border-border-strong"
            >
              {t.name} <X size={12} aria-hidden />
            </button>
          </li>
        ))}
      </ul>
      {mixed && (
        <p className="w-full text-meta text-muted sm:order-last">
          These trials don’t share setting and patient group, so they answer different questions.
        </p>
      )}
      <div className="flex gap-2">
        <Button variant="ghost" size="sm" onClick={onClear}>
          Clear
        </Button>
        <Button size="sm" onClick={onSave}>
          Save as collection
        </Button>
      </div>
    </div>
  );
}
