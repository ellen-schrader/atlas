import { supabase } from "@/lib/supabase";
import {
  type LabTrial,
  PATIENT_GROUPS,
  type PatientGroup,
  SETTINGS,
  type Setting,
  THERAPY_CLASSES,
  type TherapyClass,
} from "@/lib/trials";

/** Collections: clinical questions the lab follows, each with the trials that
 *  answer it (supabase/migrations/20261019180000_trial_collections.sql). Every
 *  member edits; the creator or a lab owner deletes. */

export interface CollectionFields {
  title: string;
  question: string | null;
  settings: Setting[];
  patient_groups: PatientGroup[];
  therapy_classes: TherapyClass[];
  comparison: string | null;
}

export interface Collection extends CollectionFields {
  id: string;
  team_id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  creator: { display_name: string | null } | null;
  trial_ids: string[];
  followers: string[];
}

export interface CollectionNote {
  id: string;
  body: string;
  created_at: string;
  author_id: string | null;
  author: { display_name: string | null } | null;
}

export interface CollectionPaper {
  added_at: string;
  papers: { id: string; title: string | null; venue: string | null; year: number | null } | null;
}

export interface CollectionDetail extends Collection {
  papers: CollectionPaper[];
  notes: CollectionNote[];
}

const BASE =
  "id, team_id, title, question, settings, patient_groups, therapy_classes, comparison, " +
  "created_by, created_at, updated_at, " +
  "creator:profiles!trial_collections_created_by_fkey(display_name), " +
  "collection_trials(trial_id), collection_followers(user_id)";

type Row = Omit<Collection, "trial_ids" | "followers"> & {
  collection_trials: { trial_id: string }[];
  collection_followers: { user_id: string }[];
};

function fromRow(r: Row): Collection {
  const { collection_trials, collection_followers, ...rest } = r;
  return {
    ...rest,
    trial_ids: collection_trials.map((t) => t.trial_id),
    followers: collection_followers.map((f) => f.user_id),
  };
}

export async function fetchCollections(teamId: string): Promise<Collection[]> {
  const { data, error } = await supabase
    .from("trial_collections")
    .select(BASE)
    .eq("team_id", teamId)
    .order("updated_at", { ascending: false });
  if (error) throw error;
  return (data as unknown as Row[]).map(fromRow);
}

export async function fetchCollection(id: string): Promise<CollectionDetail | null> {
  const { data, error } = await supabase
    .from("trial_collections")
    .select(
      `${BASE}, collection_papers(added_at, papers(id, title, venue, year)), ` +
        "collection_notes(id, body, created_at, author_id, " +
        "author:profiles!collection_notes_author_id_fkey(display_name))",
    )
    .eq("id", id)
    .maybeSingle();
  if (error) throw error;
  if (!data) return null;
  const r = data as unknown as Row & {
    collection_papers: CollectionPaper[];
    collection_notes: CollectionNote[];
  };
  const { collection_papers, collection_notes, ...row } = r;
  return {
    ...fromRow(row),
    papers: collection_papers,
    notes: [...collection_notes].sort((a, b) => a.created_at.localeCompare(b.created_at)),
  };
}

function clean(f: CollectionFields): CollectionFields {
  return {
    ...f,
    title: f.title.trim(),
    question: f.question?.trim() || null,
    comparison: f.comparison?.trim() || null,
  };
}

/** Create a collection (optionally with trials) and return its id. */
export async function createCollection(
  teamId: string,
  userId: string,
  fields: CollectionFields,
  trialIds: string[] = [],
): Promise<string> {
  const { data, error } = await supabase
    .from("trial_collections")
    .insert({ team_id: teamId, ...clean(fields), created_by: userId, updated_by: userId })
    .select("id")
    .single();
  if (error) throw error;
  const id = (data as { id: string }).id;
  if (trialIds.length) await addCollectionTrials(id, trialIds, userId);
  return id;
}

export async function updateCollection(id: string, userId: string, fields: CollectionFields) {
  const { error } = await supabase
    .from("trial_collections")
    .update({ ...clean(fields), updated_by: userId, updated_at: new Date().toISOString() })
    .eq("id", id);
  if (error) throw error;
}

/** Marks the collection as changed now, by this person (adding a trial or a
 *  paper is an edit too: "updated 3d ago" should say so). */
async function touch(id: string, userId: string) {
  await supabase
    .from("trial_collections")
    .update({ updated_by: userId, updated_at: new Date().toISOString() })
    .eq("id", id);
}

export async function deleteCollection(id: string) {
  const { data, error } = await supabase.from("trial_collections").delete().eq("id", id).select("id");
  if (error) throw error;
  if (!data.length) throw new Error("Only the person who made it, or a lab owner, can delete it.");
}

export async function addCollectionTrials(id: string, trialIds: string[], userId: string) {
  const { error } = await supabase
    .from("collection_trials")
    .upsert(
      trialIds.map((trial_id) => ({ collection_id: id, trial_id, added_by: userId })),
      { onConflict: "collection_id,trial_id", ignoreDuplicates: true },
    );
  if (error) throw error;
  await touch(id, userId);
}

export async function removeCollectionTrial(id: string, trialId: string, userId: string) {
  const { error } = await supabase
    .from("collection_trials")
    .delete()
    .eq("collection_id", id)
    .eq("trial_id", trialId);
  if (error) throw error;
  await touch(id, userId);
}

export async function addCollectionPaper(id: string, paperId: string, userId: string) {
  const { error } = await supabase
    .from("collection_papers")
    .upsert(
      { collection_id: id, paper_id: paperId, added_by: userId },
      { onConflict: "collection_id,paper_id", ignoreDuplicates: true },
    );
  if (error) throw error;
  await touch(id, userId);
}

export async function removeCollectionPaper(id: string, paperId: string, userId: string) {
  const { error } = await supabase
    .from("collection_papers")
    .delete()
    .eq("collection_id", id)
    .eq("paper_id", paperId);
  if (error) throw error;
  await touch(id, userId);
}

export async function setFollowing(id: string, userId: string, follow: boolean) {
  const { error } = follow
    ? await supabase
        .from("collection_followers")
        .upsert({ collection_id: id, user_id: userId }, { ignoreDuplicates: true })
    : await supabase
        .from("collection_followers")
        .delete()
        .eq("collection_id", id)
        .eq("user_id", userId);
  if (error) throw error;
}

export async function addNote(id: string, userId: string, body: string) {
  const { error } = await supabase
    .from("collection_notes")
    .insert({ collection_id: id, author_id: userId, body: body.trim() });
  if (error) throw error;
}

export async function deleteNote(noteId: string) {
  const { error } = await supabase.from("collection_notes").delete().eq("id", noteId);
  if (error) throw error;
}

// --- describing a question ------------------------------------------------------

/** "Neoadjuvant · TNBC": the small caps line on a tile. */
export function questionCaps(c: Pick<CollectionFields, "settings" | "patient_groups">): string {
  const parts = [
    c.settings.map((s) => SETTINGS[s]).join(" / "),
    c.patient_groups.map((g) => PATIENT_GROUPS[g]).join(", "),
  ].filter(Boolean);
  return parts.join(" · ");
}

/** What every one of these trials shares: a starting point for a new
 *  collection's tags. */
export function sharedTags(trials: LabTrial[]): Pick<
  CollectionFields,
  "settings" | "patient_groups" | "therapy_classes"
> {
  const common = <T extends string>(pick: (t: LabTrial) => T[]): T[] => {
    if (!trials.length) return [];
    const [first, ...rest] = trials.map(pick);
    return first.filter((v) => rest.every((r) => r.includes(v)));
  };
  return {
    settings: common((t) => t.facts?.settings ?? []),
    patient_groups: common((t) => t.facts?.patient_groups ?? []),
    therapy_classes: common((t) => t.facts?.therapy_classes ?? []),
  };
}

/** Whether these trials ask the same question: same setting and patient group.
 *  The tray warns when they don't ("descriptive comparison, not randomised"
 *  only holds for like with like). */
export function sameSettingAndGroup(trials: LabTrial[]): boolean {
  const key = (t: LabTrial) =>
    `${[...(t.facts?.settings ?? [])].sort()}|${[...(t.facts?.patient_groups ?? [])].sort()}`;
  return new Set(trials.map(key)).size <= 1;
}

export interface Suggestion {
  key: string;
  title: string;
  trials: LabTrial[];
  fields: CollectionFields;
}

/** Groups of two or more classified trials that share setting, patient group
 *  and the therapy classes under test (chemotherapy aside: most arms share it),
 *  and that no collection already holds together. "Adjuvant CDK4/6 inhibitor in
 *  HR+/HER2−: monarchE, NATALEE". */
export function suggestCollections(trials: LabTrial[], collections: Collection[]): Suggestion[] {
  const groups = new Map<string, LabTrial[]>();
  for (const t of trials) {
    const f = t.facts;
    if (!f?.classified_by) continue;
    const tested = f.therapy_classes.filter((c) => c !== "chemotherapy");
    if (!f.settings.length || !f.patient_groups.length || !tested.length) continue;
    const key = [f.settings, f.patient_groups, tested].map((a) => [...a].sort().join("+")).join("|");
    groups.set(key, [...(groups.get(key) ?? []), t]);
  }
  const held = collections.map((c) => new Set(c.trial_ids));
  const out: Suggestion[] = [];
  for (const [key, ts] of groups) {
    if (ts.length < 2) continue;
    if (held.some((h) => ts.every((t) => h.has(t.id)))) continue;
    const f = ts[0].facts!;
    const tested = f.therapy_classes.filter((c) => c !== "chemotherapy");
    const title =
      `${f.settings.map((s) => SETTINGS[s]).join(" / ")} ` +
      `${tested.map((c) => THERAPY_CLASSES[c]).join(" + ")} in ` +
      `${f.patient_groups.map((g) => PATIENT_GROUPS[g]).join(", ")}`;
    out.push({
      key,
      title,
      trials: ts,
      fields: {
        title,
        question: null,
        settings: f.settings,
        patient_groups: f.patient_groups,
        therapy_classes: f.therapy_classes,
        comparison: null,
      },
    });
  }
  return out.sort((a, b) => b.trials.length - a.trials.length);
}
