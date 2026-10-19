import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { type Collection, collectionsByTrial } from "@/lib/collections";
import { describe, fetchEvents, foldEvents, fromRegistry } from "@/lib/events";
import type { LabTrial } from "@/lib/trials";
import type { TrialFrom } from "@/routes/TrialPage";
import { cn, formatAgo } from "@/lib/utils";

/** "Recent updates in your collections": what changed on the trials the lab's
 *  collections hold, newest first. */
export function TrialsFeed({
  teamId,
  collections,
  trials,
}: {
  teamId: string;
  collections: Collection[];
  trials: LabTrial[];
}) {
  const events = useQuery({ queryKey: ["trial-events", teamId], queryFn: () => fetchEvents(teamId) });
  const inCollections = collectionsByTrial(collections);
  const byId = new Map(trials.map((t) => [t.id, t]));
  const items = foldEvents(events.data ?? [])
    .filter((i) => inCollections.has(i.trial_id) && byId.has(i.trial_id))
    .slice(0, 8);
  if (!items.length) return null;
  // One collection on every line says nothing: name it once, in the heading.
  const named = new Set(items.map((i) => inCollections.get(i.trial_id)![0].id));
  const only = named.size === 1 ? inCollections.get(items[0].trial_id)![0] : null;
  const from: TrialFrom = { from: { to: "/trials/collections", label: "Collections" } };
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-heading font-semibold text-fg">
        Recent updates{" "}
        {only ? (
          <>
            in{" "}
            <Link to={`/trials/collections/${only.id}`} className="hover:text-accent">
              {only.title}
            </Link>
          </>
        ) : (
          "in your collections"
        )}
      </h2>
      <p className="-mt-1 text-meta text-muted">
        <span aria-hidden className="mr-1.5 inline-block h-2 w-2 rounded-full bg-accent" />
        From ClinicalTrials.gov
        <span aria-hidden className="ml-4 mr-1.5 inline-block h-2 w-2 rounded-full bg-border-strong" />
        From the lab
      </p>
      <ul className="divide-y divide-border rounded-card border border-border bg-surface">
        {items.map((i) => {
          const t = byId.get(i.trial_id)!;
          const c = inCollections.get(i.trial_id)![0];
          const registry = fromRegistry(i.kind);
          return (
            <li key={i.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
              <span
                aria-hidden
                className={cn(
                  "h-2 w-2 shrink-0 rounded-full",
                  registry ? "bg-accent" : "bg-border-strong",
                )}
              />
              <Link
                to={`/trials/${t.nct_id}`}
                state={from}
                className="text-sm font-semibold text-fg hover:text-accent"
              >
                {t.name}
              </Link>
              {/* The registry's news (status, results) matters more than the lab's own. */}
              <span className={cn("min-w-0 flex-1 text-sm", registry ? "font-medium text-fg" : "text-muted")}>
                {describe(i)}
              </span>
              {!only && (
                <Link
                  to={`/trials/collections/${c.id}`}
                  className="max-w-56 truncate text-meta text-faint hover:text-accent"
                >
                  {c.title}
                </Link>
              )}
              <span className="w-10 shrink-0 text-right text-meta text-faint">{formatAgo(i.at)}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
