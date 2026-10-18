import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Layers, Loader2, Plus, Search, Sparkles } from "lucide-react";

import { NewCollectionDialog } from "@/components/trials/CollectionForm";
import { RequireTrials, TherapySwatch, TrialsDisclaimer } from "@/components/trials/parts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type Collection,
  type Suggestion,
  fetchCollections,
  questionCaps,
  suggestCollections,
} from "@/lib/collections";
import { type LabTrial, THERAPY_CLASSES, fetchLabTrials } from "@/lib/trials";
import { cn, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

export default function TrialCollections() {
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

function Collections() {
  const { team, userId } = useAppContext();
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

  const all = collections.data ?? [];
  // Quick chips: the therapy classes the lab's collections are about.
  const chips = [...new Set(all.flatMap((c) => c.therapy_classes))].filter(
    (c) => c !== "chemotherapy",
  );
  const needle = query.trim().toLowerCase();
  const shown = all.filter((c) => {
    const names = c.trial_ids.map((id) => byId.get(id)?.name ?? "").join(" ");
    const hay = `${c.title} ${c.question ?? ""} ${questionCaps(c)} ${names}`.toLowerCase();
    return (!needle || hay.includes(needle)) && (!chip || c.therapy_classes.includes(chip as never));
  });
  const suggestion =
    !needle && !chip
      ? suggestCollections(trials.data ?? [], all).find((s) => !dismissed.has(s.key))
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
            No collections yet. Start one for a question the lab keeps coming back to, or select
            trials in <Link to="/trials" className="text-accent hover:underline">All trials</Link>{" "}
            and save them as a collection.
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
            <CollectionTile key={c.id} c={c} trials={c.trial_ids.map((id) => byId.get(id))} />
          ))}
        </div>
      )}

      <TrialsDisclaimer />

      <NewCollectionDialog
        open={creating !== null}
        onClose={() => setCreating(null)}
        teamId={team.id}
        userId={userId}
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

function CollectionTile({ c, trials }: { c: Collection; trials: (LabTrial | undefined)[] }) {
  const lead = c.therapy_classes.find((t) => t !== "chemotherapy") ?? c.therapy_classes[0];
  const known = trials.filter(Boolean) as LabTrial[];
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
        {c.creator?.display_name && ` · created by ${c.creator.display_name}`} · updated{" "}
        {formatRelative(c.updated_at)}
      </div>
    </Link>
  );
}
