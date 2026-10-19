import { supabase } from "@/lib/supabase";
import { statusLabel } from "@/lib/trials";

/** What changed on the lab's trials (public.trial_events), for the feed. */

export interface TrialEvent {
  id: string;
  trial_id: string;
  kind:
    | "registry_updated"
    | "status_changed"
    | "results_posted"
    | "paper_linked"
    | "extraction_done"
    | "values_verified";
  detail: Record<string, unknown>;
  created_at: string;
  actor: { display_name: string | null } | null;
}

/** An entry in the feed: repeats of the same kind on the same trial and day
 *  ("verified 6 groups") fold into one. */
export interface FeedItem {
  key: string;
  trial_id: string;
  kind: TrialEvent["kind"];
  count: number;
  who: string | null;
  detail: Record<string, unknown>;
  at: string;
}

export async function fetchEvents(teamId: string, days = 30): Promise<TrialEvent[]> {
  const since = new Date(Date.now() - days * 86_400_000).toISOString();
  const { data, error } = await supabase
    .from("trial_events")
    .select("id, trial_id, kind, detail, created_at, actor:profiles!trial_events_actor_fkey(display_name)")
    .eq("team_id", teamId)
    .gte("created_at", since)
    .order("created_at", { ascending: false })
    .limit(200);
  if (error) throw error;
  return data as unknown as TrialEvent[];
}

export function foldEvents(events: TrialEvent[]): FeedItem[] {
  const out = new Map<string, FeedItem>();
  for (const e of events) {
    // Per person too: one line never credits Bob's checks to Ada.
    const key = `${e.trial_id}|${e.kind}|${e.created_at.slice(0, 10)}|${e.actor?.display_name ?? ""}`;
    const item = out.get(key);
    if (item) item.count += 1;
    else
      out.set(key, {
        key,
        trial_id: e.trial_id,
        kind: e.kind,
        count: 1,
        who: e.actor?.display_name ?? null,
        detail: e.detail,
        at: e.created_at,
      });
  }
  return [...out.values()];
}

const STATUS = (s: unknown) => statusLabel(typeof s === "string" ? s : null);

export function describe(i: FeedItem): string {
  switch (i.kind) {
    case "registry_updated":
      return "Updated on ClinicalTrials.gov";
    case "status_changed":
      return `Status changed: ${STATUS(i.detail.from)} → ${STATUS(i.detail.to)}`;
    case "results_posted":
      return "Results posted on ClinicalTrials.gov";
    case "paper_linked":
      return i.count > 1 ? `${i.count} papers linked` : "New paper linked";
    case "extraction_done":
      return "Data extracted from the papers";
    case "values_verified":
      return `${i.count === 1 ? "A value group" : `${i.count} value groups`} verified${i.who ? ` by ${i.who}` : ""}`;
  }
}

/** Atlas's own news (the registry) reads as more urgent than the lab's. */
export const fromRegistry = (k: TrialEvent["kind"]) =>
  k === "registry_updated" || k === "status_changed" || k === "results_posted";
