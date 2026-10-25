import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Layers, Loader2, Plus, Search, Sparkles } from "lucide-react";

import { NewCollectionDialog } from "@/components/trials/CollectionForm";
import { TrialsFeed } from "@/components/trials/TrialsFeed";
import { RequireTrials, TherapySwatch, TrialsDisclaimer } from "@/components/trials/parts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import {
  type Collection,
  type Suggestion,
  fetchCollections,
  fetchLabEndpoints,
  questionCaps,
  suggestCollections,
} from "@/lib/collections";
import {
  hrDomain,
  hrLabel,
  hrOf,
  pcrDelta,
  pcrDomain,
  pcrOf,
  sharedHrEndpoint,
} from "@/lib/compare";
import type { Endpoint, Extraction } from "@/lib/extraction";
import {
  type LabTrial,
  THERAPY_CLASSES,
  THERAPY_COLOR,
  type TherapyClass,
  fetchLabTrials,
} from "@/lib/trials";
import { cn, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

export default function TrialCollections() {
  useDocumentTitle("Collections");
  return (
    <RequireTrials>
      <Collections />
    </RequireTrials>
  );
}

/** Dismissed suggestions, per viewer and lab: a convenience, so browser
 *  storage (and it may be unavailable). */
function useDismissed(teamId: string): [Set<string>, (key: string) => void] {
  const storageKey = `atlas:dismissed-collection-suggestions:${teamId}`;
  const read = () => {
    try {
      return new Set<string>(JSON.parse(localStorage.getItem(storageKey) ?? "[]"));
    } catch {
      return new Set<string>();
    }
  };
  const [dismissed, setDismissed] = useState(read);
  // Each lab has its own list: read it again when the lab changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => setDismissed(read()), [storageKey]);
  const dismiss = (key: string) => {
    const next = new Set(dismissed).add(key);
    setDismissed(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify([...next]));
    } catch {
      /* private window: dismissed for this visit only */
    }
  };
  return [dismissed, dismiss];
}

/** A collection's therapy classes: its own tags, else its trials' (a
 *  collection made without tags still gets its colour and its chip). */
function therapiesOf(c: Collection, byId: Map<string, LabTrial>): TherapyClass[] {
  if (c.therapy_classes.length) return c.therapy_classes;
  return [...new Set(c.trial_ids.flatMap((id) => byId.get(id)?.facts?.therapy_classes ?? []))];
}

function Collections() {
  const { team } = useAppContext();
  const [query, setQuery] = useState("");
  const [chip, setChip] = useState<string | null>(null);
  const [creating, setCreating] = useState<Suggestion | "blank" | null>(null);
  const [dismissed, dismiss] = useDismissed(team.id);

  const collections = useQuery({
    queryKey: ["collections", team.id],
    queryFn: () => fetchCollections(team.id),
  });
  const trials = useQuery({
    queryKey: ["lab-trials", team.id],
    queryFn: () => fetchLabTrials(team.id),
  });
  const byId = new Map((trials.data ?? []).map((t) => [t.id, t]));
  const endpoints = useQuery({
    queryKey: ["lab-endpoints", team.id],
    queryFn: () => fetchLabEndpoints(team.id),
  });

  const all = collections.data ?? [];
  // Quick chips: the therapy classes the lab's collections are about.
  const chips = [...new Set(all.flatMap((c) => therapiesOf(c, byId)))].filter(
    (c) => c !== "chemotherapy",
  );
  const needle = query.trim().toLowerCase();
  const shown = all.filter((c) => {
    const names = c.trial_ids.map((id) => byId.get(id)?.name ?? "").join(" ");
    const hay = `${c.title} ${c.question ?? ""} ${questionCaps(c)} ${names}`.toLowerCase();
    return (!needle || hay.includes(needle)) && (!chip || therapiesOf(c, byId).includes(chip as never));
  });
  // Only once both have loaded: before the collections arrive, every group
  // would look new and a quick click could duplicate a collection.
  const suggestion =
    !needle && !chip && collections.data && trials.data
      ? suggestCollections(trials.data, collections.data).find((s) => !dismissed.has(s.key))
      : undefined;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6 sm:p-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-display font-bold tracking-tight text-fg">Collections</h1>
          <p className="mt-1.5 max-w-[64ch] text-sm text-muted">
            The clinical questions {team.name} follows, each with the trials that answer it.
          </p>
        </div>
        <Button onClick={() => setCreating("blank")}>
          <Plus size={16} aria-hidden /> New collection
        </Button>
      </header>

      {(collections.isLoading || trials.isLoading) && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 size={14} className="animate-spin" aria-hidden /> Loading…
        </p>
      )}
      {collections.error && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load the collections. Try again.
        </p>
      )}

      {all.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative min-w-60 flex-1 sm:max-w-sm">
            <span className="sr-only">Search collections</span>
            <Search
              size={15}
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
            />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search questions and trials"
              className="pl-9"
            />
          </label>
          {chips.map((c) => (
            <button
              key={c}
              type="button"
              aria-pressed={chip === c}
              onClick={() => setChip(chip === c ? null : c)}
              className={cn(
                "inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-sm transition",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                chip === c
                  ? "border-accent/50 bg-accent-weak text-fg"
                  : "border-border text-muted hover:text-fg",
              )}
            >
              <TherapySwatch therapy={c} />
              {THERAPY_CLASSES[c]}
            </button>
          ))}
        </div>
      )}

      {suggestion && (
        <div className="flex flex-wrap items-center gap-4 rounded-card border border-dashed border-accent/40 bg-accent-weak/40 p-4">
          <Sparkles size={18} aria-hidden className="shrink-0 text-accent" />
          <div className="min-w-0 flex-1">
            <div className="text-eyebrow font-semibold uppercase tracking-eyebrow text-accent">
              Suggested collection
            </div>
            <div className="mt-0.5 font-semibold text-fg">{suggestion.title}</div>
            <p className="text-sm text-muted">
              {suggestion.trials.length} trials share setting, patient group and therapy class:{" "}
              {suggestion.trials.map((t) => t.name).join(", ")}
            </p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => setCreating(suggestion)}>
              Create collection
            </Button>
            <Button size="sm" variant="ghost" onClick={() => dismiss(suggestion.key)}>
              Dismiss
            </Button>
          </div>
        </div>
      )}

      {collections.data && all.length === 0 && !suggestion && (
        <div className="flex flex-col items-start gap-3 rounded-card border border-dashed border-border-strong p-6">
          <Layers size={20} className="text-muted" aria-hidden />
          <p className="max-w-[60ch] text-sm text-muted">
            No collections yet. Tick trials in{" "}
            <Link to="/trials" className="text-accent hover:underline">All trials</Link> and save
            them as a collection.
          </p>
        </div>
      )}

      {all.length > 0 && shown.length === 0 && (
        <p className="text-sm text-muted">
          No collections match.{" "}
          <Link to="/trials" className="text-accent hover:underline">
            Search all trials instead
          </Link>
        </p>
      )}

      {shown.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {shown.map((c) => (
            <CollectionTile
              key={c.id}
              c={c}
              therapies={therapiesOf(c, byId)}
              trials={c.trial_ids.map((id) => byId.get(id))}
              endpoints={endpoints.data}
            />
          ))}
        </div>
      )}

      {collections.data && trials.data && !needle && !chip && (
        <TrialsFeed teamId={team.id} collections={collections.data} trials={trials.data} />
      )}

      <TrialsDisclaimer />

      <NewCollectionDialog
        open={creating !== null}
        onClose={() => setCreating(null)}
        teamId={team.id}
        initial={creating && creating !== "blank" ? creating.fields : undefined}
        trialIds={creating && creating !== "blank" ? creating.trials.map((t) => t.id) : []}
        note={
          creating && creating !== "blank"
            ? `With ${creating.trials.map((t) => t.name).join(", ")}.`
            : undefined
        }
      />
    </div>
  );
}

function CollectionTile({
  c,
  therapies,
  trials,
  endpoints,
}: {
  c: Collection;
  therapies: TherapyClass[];
  trials: (LabTrial | undefined)[];
  endpoints?: Map<string, Endpoint[]>;
}) {
  const lead = therapies.find((t) => t !== "chemotherapy") ?? therapies[0];
  const known = trials.filter(Boolean) as LabTrial[];
  const withData = known.filter((t) => t.facts?.extracted_at).length;
  return (
    <Link
      to={`/trials/collections/${c.id}`}
      className="relative flex flex-col gap-2 overflow-hidden rounded-card border border-border bg-surface p-5 pl-6 transition hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      {lead && (
        <span aria-hidden className="absolute inset-y-0 left-0 w-[3px]">
          <TherapySwatch therapy={lead} className="h-full w-full rounded-none" />
        </span>
      )}
      <div className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
        {questionCaps(c) || "Untagged"}
      </div>
      <div className="text-card font-semibold text-fg">{c.title}</div>
      {c.question && <p className="line-clamp-2 text-sm text-muted">{c.question}</p>}
      {known.length > 0 && endpoints && (
        <MiniPlot
          trials={known}
          endpoints={endpoints}
          colour={lead ? THERAPY_COLOR[lead] : "var(--ch-1)"}
        />
      )}
      {known.length > 0 && withData === 0 && (
        <p className="rounded-control border border-dashed border-border px-3 py-2 text-meta text-muted">
          No results yet. Open the collection to get its trials’ data.
        </p>
      )}
      {known.length > 0 ? (
        <ul className="mt-1 flex flex-wrap gap-1.5">
          {known.map((t) => (
            <li
              key={t.id}
              className="rounded-chip border border-border bg-surface-2 px-2 py-0.5 text-meta text-fg"
            >
              {t.name}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-meta text-faint">No trials yet</p>
      )}
      <div className="mt-auto pt-2 text-meta text-muted">
        {known.length} {known.length === 1 ? "trial" : "trials"}
        {known.length > 0 && ` · ${withData === known.length ? "all" : withData} with data`}
        {c.creator?.display_name && ` · created by ${c.creator.display_name}`} · updated{" "}
        {formatRelative(c.updated_at)}
      </div>
    </Link>
  );
}

/** The tile's plot: each trial's pCR (control hollow → experimental filled)
 *  if any trial reports one, else its hazard ratio on a log axis. Trials
 *  without extracted data are left out; the tile's list still names them. */
function MiniPlot({
  trials,
  endpoints,
  colour,
}: {
  trials: LabTrial[];
  endpoints: Map<string, Endpoint[]>;
  colour: string;
}) {
  const asX = (t: LabTrial) => ({ endpoints: endpoints.get(t.id) ?? [] }) as unknown as Extraction;
  const pcr = trials.flatMap((t) => {
    const e = pcrOf(asX(t));
    return e ? [{ t, c: e.ctrl_value!, x: e.exp_value!, d: pcrDelta(e) }] : [];
  });
  const hrName = pcr.length ? null : sharedHrEndpoint(trials.map((t) => ({ id: t.id, name: t.name, extraction: asX(t) })));
  const hr = hrName
    ? trials.flatMap((t) => {
        const e = hrOf(asX(t), hrName);
        return e ? [{ t, hr: e.hr!, lo: e.hr_ci_low, hi: e.hr_ci_high }] : [];
      })
    : [];
  if (!pcr.length && !hr.length) return null;

  // Axes fitted to the data (as in Compare), so no value is pinned to an edge.
  const [pLo, pHi] = pcrDomain(pcr.flatMap(({ c, x }) => [c, x]));
  const [hLo, hHi] = hrDomain(hr.flatMap(({ hr: v, lo, hi }) => [v, lo ?? v, hi ?? v]));
  const pP = (v: number) => ((v - pLo) / (pHi - pLo)) * 100;
  const hP = (v: number) => ((Math.log(v) - Math.log(hLo)) / (Math.log(hHi) - Math.log(hLo))) * 100;
  const label = pcr.length
    ? `pCR, control ○ to experimental ● (axis ${pLo}–${pHi}%)`
    : `${hrLabel(hrName!)} hazard ratio (95% CI)`;

  return (
    <div className="mt-1 flex flex-col gap-1" aria-label={label}>
      <div className="text-meta text-faint">{label}</div>
      {pcr.map(({ t, c, x, d }) => (
        <div key={t.id} className="grid grid-cols-[96px_1fr_4.5rem] items-center gap-2" title={`${t.name}: ${c}% → ${x}%`}>
          <span className="truncate text-meta text-muted">{t.name}</span>
          <div className="relative h-3">
            <div
              className="absolute top-1/2 h-[2px] -translate-y-1/2 opacity-60"
              style={{ left: `${pP(Math.min(c, x))}%`, width: `${Math.abs(pP(x) - pP(c))}%`, background: colour }}
            />
            <span
              className="absolute top-0 h-3 w-3 -translate-x-1/2 rounded-full border-2 bg-surface"
              style={{ left: `${pP(c)}%`, borderColor: colour }}
            />
            <span className="absolute top-0 h-3 w-3 -translate-x-1/2 rounded-full" style={{ left: `${pP(x)}%`, background: colour }} />
          </div>
          {/* One line: "+13.6 pp" must not wrap, and the column is the same on
              every row so the bars share one axis. */}
          <span className="whitespace-nowrap text-right font-mono text-meta text-fg">
            {d >= 0 ? "+" : ""}
            {d} pp
          </span>
        </div>
      ))}
      {hr.map(({ t, hr: v, lo, hi }) => (
        <div key={t.id} className="grid grid-cols-[96px_1fr_4.5rem] items-center gap-2" title={`${t.name}: HR ${v}${lo != null && hi != null ? ` (${lo}–${hi})` : ""}`}>
          <span className="truncate text-meta text-muted">{t.name}</span>
          <div className="relative h-3">
            <div className="absolute inset-y-0 w-px bg-border-strong" style={{ left: `${hP(1)}%` }} />
            {lo != null && hi != null && (
              <div
                className="absolute top-1/2 h-[2px] -translate-y-1/2"
                style={{ left: `${hP(lo)}%`, width: `${hP(hi) - hP(lo)}%`, background: colour }}
              />
            )}
            <span className="absolute top-0 h-3 w-3 -translate-x-1/2 rounded-full" style={{ left: `${hP(v)}%`, background: colour }} />
          </div>
          <span className="whitespace-nowrap text-right font-mono text-meta text-fg">{v}</span>
        </div>
      ))}
    </div>
  );
}
