import { supabase } from "@/lib/supabase";

/** Clinical trials (docs/CLINICAL_TRIALS_PLAN.md). Dark unless the
 *  `clinical_trials` feature is on for the lab or the person. */
export const TRIALS_FEATURE = "clinical_trials";

// --- the breast cancer taxonomy --------------------------------------------
// Keys are what's stored. Keep in step with paper_radar/trials/taxonomy.py and
// the checks in supabase/migrations/20261019170000_trial_facts.sql.

export const SETTINGS = {
  neoadjuvant: "Neoadjuvant",
  adjuvant: "Adjuvant",
  metastatic: "Metastatic",
} as const;

export const PATIENT_GROUPS = {
  tnbc: "TNBC",
  hr_pos_her2_neg: "HR+/HER2−",
  her2_pos: "HER2+",
  her2_low: "HER2-low",
  gbrca: "gBRCA",
} as const;

export const THERAPY_CLASSES = {
  immunotherapy: "Immunotherapy",
  adc: "ADC",
  cdk46: "CDK4/6 inhibitor",
  parp: "PARP inhibitor",
  her2_targeted: "HER2-targeted",
  other_targeted: "Other targeted",
  endocrine: "Endocrine",
  chemotherapy: "Chemotherapy",
} as const;

export type Setting = keyof typeof SETTINGS;
export type PatientGroup = keyof typeof PATIENT_GROUPS;
export type TherapyClass = keyof typeof THERAPY_CLASSES;

/** Therapy class colours, from the app's data channels (charts only, never
 *  chrome). Targeted therapies share one channel, as in the mock-up;
 *  chemotherapy is the neutral "off" channel, the backbone most arms share. */
export const THERAPY_COLOR: Record<TherapyClass, string> = {
  immunotherapy: "var(--ch-1)",
  adc: "var(--ch-5)",
  cdk46: "var(--ch-4)",
  parp: "var(--ch-4)",
  her2_targeted: "var(--ch-2)",
  other_targeted: "var(--ch-4)",
  endocrine: "var(--ch-3)",
  chemotherapy: "var(--ch-off)",
};

/** "PHASE3" → "Phase III"; "PHASE1","PHASE2" → "Phase I/II". */
export function phaseLabel(phases: string[]): string {
  const roman: Record<string, string> = {
    EARLY_PHASE1: "Early I",
    PHASE1: "I",
    PHASE2: "II",
    PHASE3: "III",
    PHASE4: "IV",
  };
  const parts = phases.map((p) => roman[p]).filter(Boolean);
  return parts.length ? `Phase ${parts.join("/")}` : "Phase n/a";
}

/** "ACTIVE_NOT_RECRUITING" → "Active, not recruiting". */
export function statusLabel(status: string | null): string {
  if (!status) return "Status unknown";
  const s = status.toLowerCase().replace(/_/g, " ");
  return (s.charAt(0).toUpperCase() + s.slice(1)).replace(" not ", ", not ");
}

export function ctgovUrl(nct: string): string {
  return `https://clinicaltrials.gov/study/${nct}`;
}

// --- rows ------------------------------------------------------------------

export interface Trial {
  id: string;
  nct_id: string;
  acronym: string | null;
  title: string;
  phases: string[];
  status: string | null;
  sponsor: string | null;
  conditions: string[];
  enrollment: number | null;
  start_date: string | null;
  completion_date: string | null;
  has_results: boolean;
}

export interface TrialFacts {
  trial_id: string;
  acronym: string | null;
  settings: Setting[];
  patient_groups: PatientGroup[];
  therapy_classes: TherapyClass[];
  classified_by: "claude" | "person" | null;
  classify_attempts: number;
  classify_claimed_at: string | null;
  extraction: import("@/lib/extraction").Extraction | null;
  extraction_status: "queued" | "batched" | "running" | "done" | "failed" | null;
  extraction_queued_at: string | null;
  extraction_mode: "batch" | "now" | "claude" | null;
  extraction_error: string | null;
  extraction_started_at: string | null;
  extracted_at: string | null;
  extraction_model: string | null;
  extraction_cost_usd: number | null;
  extraction_sources: string[] | null;
  updated_by: string | null;
  updated_at: string;
}

/** A trial on the lab's list, with what the lab knows about it. */
export interface LabTrial extends Trial {
  /** The lab's short name, else the registry's, else the NCT ID. */
  name: string;
  added: "manual" | "paper";
  added_at: string;
  facts: TrialFacts | null;
  /** Linked papers (automatic or confirmed). */
  papers: number;
  /** Suggested links waiting for someone to confirm or reject them. */
  suggestions: number;
}

/** Where Claude's classification stands: "done", "pending" (just added, or a
 *  task is working on it: worth waiting for) or "missing" (it didn't happen;
 *  someone can set it on the trial page). */
export function classification(
  facts: TrialFacts | null,
  addedAt: string,
  now = Date.now(),
): "done" | "pending" | "missing" {
  if (facts?.classified_by) return "done";
  const recent = (iso: string | null | undefined, ms: number) =>
    !!iso && now - new Date(iso).getTime() < ms;
  if (recent(addedAt, 3 * 60_000) || recent(facts?.classify_claimed_at, 2 * 60_000))
    return "pending";
  return "missing";
}

const FACT_COLUMNS =
  "trial_id, acronym, settings, patient_groups, therapy_classes, classified_by, " +
  "classify_attempts, classify_claimed_at, extraction_status, extraction_started_at, extracted_at, " +
  "updated_by, updated_at";

export const TRIAL_COLUMNS =
  "id, nct_id, acronym, title, phases, status, sponsor, conditions, enrollment, " +
  "start_date, completion_date, has_results";

export function trialName(t: Pick<Trial, "acronym" | "nct_id">, facts?: TrialFacts | null) {
  return facts?.acronym?.trim() || t.acronym || t.nct_id;
}

export async function fetchLabTrials(teamId: string): Promise<LabTrial[]> {
  const [posts, facts, links] = await Promise.all([
    supabase
      .from("trial_posts")
      .select(`source, created_at, trials(${TRIAL_COLUMNS})`)
      .eq("team_id", teamId),
    // Not the extraction: the list doesn't show it, and it's the heavy column.
    supabase.from("trial_facts").select(FACT_COLUMNS).eq("team_id", teamId),
    supabase
      .from("paper_trials")
      .select("trial_id, status")
      .eq("team_id", teamId)
      .in("status", ["auto", "confirmed", "suggested"]),
  ]);
  for (const r of [posts, facts, links]) if (r.error) throw r.error;

  const factsBy = new Map(
    (facts.data as unknown as TrialFacts[]).map((f) => [f.trial_id, { ...f, extraction: null }]),
  );
  const linked = new Map<string, number>();
  const suggested = new Map<string, number>();
  for (const l of links.data as { trial_id: string; status: string }[]) {
    const m = l.status === "suggested" ? suggested : linked;
    m.set(l.trial_id, (m.get(l.trial_id) ?? 0) + 1);
  }
  type PostRow = { source: "manual" | "paper"; created_at: string; trials: Trial | null };
  return (posts.data as unknown as PostRow[])
    .filter((p) => p.trials)
    .map((p) => {
      const t = p.trials as Trial;
      const f = factsBy.get(t.id) ?? null;
      return {
        ...t,
        name: trialName(t, f),
        added: p.source,
        added_at: p.created_at,
        facts: f,
        papers: linked.get(t.id) ?? 0,
        suggestions: suggested.get(t.id) ?? 0,
      };
    });
}

// --- one trial ---------------------------------------------------------------

export interface TrialLink {
  id: string;
  paper_id: string;
  source: "nct_in_abstract" | "acronym_in_title" | "manual";
  status: "auto" | "suggested" | "confirmed" | "rejected";
  role: string | null;
  reviewed_at: string | null;
  papers: { id: string; title: string | null; venue: string | null; year: number | null } | null;
}

export interface TrialDetail {
  trial: Trial & { registry: Registry };
  added: "manual" | "paper";
  added_at: string;
  facts: TrialFacts | null;
  links: TrialLink[];
}

/** The parts of ClinicalTrials.gov's protocolSection the page reads. */
export interface Registry {
  identificationModule?: { officialTitle?: string };
  descriptionModule?: { briefSummary?: string };
  designModule?: {
    designInfo?: {
      allocation?: string;
      interventionModel?: string;
      maskingInfo?: { masking?: string };
    };
    enrollmentInfo?: { count?: number; type?: string };
  };
  armsInterventionsModule?: {
    armGroups?: { label: string; type?: string; description?: string; interventionNames?: string[] }[];
  };
  outcomesModule?: {
    primaryOutcomes?: { measure: string; timeFrame?: string }[];
    secondaryOutcomes?: { measure: string; timeFrame?: string }[];
  };
  eligibilityModule?: { eligibilityCriteria?: string; sex?: string; minimumAge?: string };
  contactsLocationsModule?: { locations?: { country?: string; status?: string }[] };
}

/** null when the trial isn't on the lab's list (or the feature is off). */
export async function fetchTrialDetail(teamId: string, nct: string): Promise<TrialDetail | null> {
  const post = await supabase
    .from("trial_posts")
    .select(`source, created_at, trials!inner(${TRIAL_COLUMNS}, registry)`)
    .eq("team_id", teamId)
    .eq("trials.nct_id", nct)
    .maybeSingle();
  if (post.error) throw post.error;
  if (!post.data) return null;
  const trial = (post.data as unknown as { trials: TrialDetail["trial"] }).trials;
  const [facts, links] = await Promise.all([
    supabase
      .from("trial_facts")
      .select("*")
      .eq("team_id", teamId)
      .eq("trial_id", trial.id)
      .maybeSingle(),
    supabase
      .from("paper_trials")
      .select("id, paper_id, source, status, role, reviewed_at, papers(id, title, venue, year)")
      .eq("team_id", teamId)
      .eq("trial_id", trial.id)
      .order("created_at"),
  ]);
  if (facts.error) throw facts.error;
  if (links.error) throw links.error;
  return {
    trial,
    added: (post.data as { source: "manual" | "paper" }).source,
    added_at: (post.data as { created_at: string }).created_at,
    facts: facts.data as TrialFacts | null,
    links: links.data as unknown as TrialLink[],
  };
}

export interface FactsEdit {
  acronym: string | null;
  settings: Setting[];
  patient_groups: PatientGroup[];
  therapy_classes: TherapyClass[];
}

/** Save the lab's correction, as the user (RLS checks the lab and the switch).
 *  Update first, insert if there's no row yet: an upsert would also write the
 *  key columns, which members may not update. */
export async function saveFacts(teamId: string, trialId: string, userId: string, edit: FactsEdit) {
  const now = new Date().toISOString();
  const row = {
    ...edit,
    acronym: edit.acronym?.trim() || null,
    classified_by: "person" as const,
    classified_at: now,
    updated_by: userId,
    updated_at: now,
  };
  const updated = await supabase
    .from("trial_facts")
    .update(row)
    .eq("team_id", teamId)
    .eq("trial_id", trialId)
    .select("trial_id");
  if (updated.error) throw updated.error;
  if (updated.data.length) return;
  const { error } = await supabase
    .from("trial_facts")
    .insert({ team_id: teamId, trial_id: trialId, ...row });
  if (error?.code === "23505") {
    // Someone (or Claude) created the row between our update and insert.
    const again = await supabase
      .from("trial_facts")
      .update(row)
      .eq("team_id", teamId)
      .eq("trial_id", trialId);
    if (again.error) throw again.error;
    return;
  }
  if (error) throw error;
}

export async function decideLink(linkId: string, userId: string, status: "confirmed" | "rejected") {
  const { error } = await supabase
    .from("paper_trials")
    .update({ status, reviewed_by: userId, reviewed_at: new Date().toISOString() })
    .eq("id", linkId);
  if (error) throw error;
}

export async function linkPaper(teamId: string, trialId: string, paperId: string, userId: string) {
  const { error } = await supabase.from("paper_trials").insert({
    team_id: teamId,
    trial_id: trialId,
    paper_id: paperId,
    source: "manual",
    status: "confirmed",
    reviewed_by: userId,
    reviewed_at: new Date().toISOString(),
  });
  if (error) throw error;
}

export async function removeTrial(teamId: string, trialId: string) {
  const { error } = await supabase
    .from("trial_posts")
    .delete()
    .eq("team_id", teamId)
    .eq("trial_id", trialId);
  if (error) throw error;
}

/** A country a trial has sites in, and how many. */
export type SiteCountry = { country: string; sites: number };
/** Where each of the lab's trials (by id) has sites, most sites first. */
export type SiteCountries = Record<string, SiteCountry[]>;

const bySites = (a: SiteCountry, b: SiteCountry) =>
  b.sites - a.sites || a.country.localeCompare(b.country);

/** Countries one registry record has sites in, most sites first. Sites, not
 *  participants: the registry doesn't say how many each enrolled. Withdrawn
 *  sites (never opened) don't count. trial_site_countries() in the database
 *  counts the lab's trials the same way. */
export function siteCountries(registry: Registry | null | undefined): SiteCountry[] {
  const counts = new Map<string, number>();
  const locations = registry?.contactsLocationsModule?.locations;
  for (const loc of Array.isArray(locations) ? locations : []) {
    if (!loc || typeof loc !== "object" || loc.status === "WITHDRAWN") continue;
    const country = typeof loc.country === "string" ? loc.country.trim() : "";
    if (country) counts.set(country, (counts.get(country) ?? 0) + 1);
  }
  return [...counts].map(([country, sites]) => ({ country, sites })).sort(bySites);
}

/** Where each of the lab's trials has sites, counted in the database from the
 *  stored registry records (no call to ClinicalTrials.gov). */
export async function fetchTrialCountries(teamId: string): Promise<SiteCountries> {
  const { data, error } = await supabase.rpc("trial_site_countries", { p_team: teamId });
  if (error) throw error;
  const out: SiteCountries = {};
  for (const r of (data ?? []) as { trial_id: string; country: string; sites: number }[])
    (out[r.trial_id] ??= []).push({ country: r.country, sites: r.sites });
  for (const list of Object.values(out)) list.sort(bySites);
  return out;
}

/** "13 countries", "Germany only": where a trial's sites are, in a few words. */
export function countriesSummary(countries: SiteCountry[]): string {
  if (countries.length === 0) return "No sites listed";
  if (countries.length === 1) return `${countries[0].country} only`;
  return `${countries.length} countries`;
}
