import { supabase } from "@/lib/supabase";

/** What Claude extracted from a trial's papers (trial_facts.extraction).
 *  Mirrors paper_radar/trials/extraction.py. */

export interface Source {
  doc: number;
  where: string;
  page: string | null;
}

export interface Endpoint {
  name: string;
  role: "primary" | "co_primary" | "key_secondary" | "secondary" | "exploratory";
  kind: "rate" | "hazard_ratio";
  definition: string | null;
  timepoint: string | null;
  exp_value: number | null;
  ctrl_value: number | null;
  difference: number | null;
  difference_ci_low: number | null;
  difference_ci_high: number | null;
  hr: number | null;
  hr_ci_low: number | null;
  hr_ci_high: number | null;
  events: number | null;
  median_followup_months: number | null;
  p_value: string | null;
  source: Source | null;
}

export type PhaseKind =
  | "chemotherapy"
  | "surgery"
  | "radiotherapy"
  | "immunotherapy"
  | "adc"
  | "targeted"
  | "endocrine"
  | "observation"
  | "other";

export interface Phase {
  label: string;
  kind: PhaseKind;
  weeks: number | null;
  experimental_add: string | null;
  control_add: string | null;
}

export interface Category {
  label: string;
  eligibility: "allowed" | "conditional" | "not_allowed" | "unknown";
  condition: string | null;
  overall_pct: number | null;
  exp_pct: number | null;
  ctrl_pct: number | null;
}

export interface Dimension {
  key: string;
  categories: Category[];
  not_reported_pct: number | null;
  assay: string | null;
  source: Source | null;
}

export interface Extraction {
  pico: { population: string; intervention: string; comparator: string; outcome: string };
  design: {
    phase: string | null;
    randomisation_ratio: string | null;
    blinding: string | null;
    analysis_population: string | null;
    data_cutoff: string | null;
    source: Source | null;
  };
  arms: {
    role: "experimental" | "control";
    label: string;
    n_randomised: number | null;
    n_analysed: number | null;
    source: Source | null;
  }[];
  schedule: Phase[];
  endpoints: Endpoint[];
  adverse_events: { label: string; exp_pct: number | null; ctrl_pct: number | null; source: Source | null }[];
  enrolment: {
    n_screened: number | null;
    n_randomised: number | null;
    n_analysed: number | null;
    dimensions: Dimension[];
    source: Source | null;
  };
  context: { key: string; value: string; source: Source | null }[];
  caveats: string | null;
}

export const DIMENSION_LABELS: Record<string, string> = {
  t_stage: "Clinical T stage",
  nodal_status: "Nodal status",
  overall_stage: "Overall stage",
  ecog: "ECOG",
  tils: "Stromal TILs",
  age: "Age",
  pdl1: "PD-L1",
  menopausal_status: "Menopausal status",
};

export const CONTEXT_LABELS: Record<string, string> = {
  pcr_definition: "pCR definition",
  pathology_review: "Pathology review",
  efs_events_counted: "EFS events counted",
  followup: "Follow-up at cut-off",
  post_surgery_therapy: "Therapy after surgery",
  enrolment_years: "Enrolment years",
  region: "Region",
  pdl1_assay: "PD-L1 assay",
};

export const ROLE_LABELS: Record<Endpoint["role"], string> = {
  primary: "Primary",
  co_primary: "Co-primary",
  key_secondary: "Key secondary",
  secondary: "Secondary",
  exploratory: "Exploratory",
};

// --- sources ------------------------------------------------------------------

export interface TrialSource {
  id: string;
  paper_id: string | null;
  kind: "paper" | "supplement";
  origin: "upload" | "europepmc";
  storage_path: string;
  filename: string;
  media_type: string;
  bytes: number;
  added_at: string;
}

const BUCKET = "trial-sources";
export const MAX_UPLOAD_BYTES = 40 * 1024 * 1024;

export async function fetchSources(teamId: string, trialId: string): Promise<TrialSource[]> {
  const { data, error } = await supabase
    .from("trial_sources")
    .select("id, paper_id, kind, origin, storage_path, filename, media_type, bytes, added_at")
    .eq("team_id", teamId)
    .eq("trial_id", trialId)
    .order("kind")
    .order("added_at");
  if (error) throw error;
  return data as TrialSource[];
}

/** Upload a PDF into the lab's private folder for this trial, then record it. */
export async function uploadSource(
  teamId: string,
  trialId: string,
  userId: string,
  file: File,
  kind: "paper" | "supplement",
) {
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf"))
    throw new Error("Only PDFs can be added.");
  if (file.size > MAX_UPLOAD_BYTES) throw new Error("That PDF is over 40 MB.");
  const path = `${teamId}/${trialId}/${crypto.randomUUID()}.pdf`;
  const up = await supabase.storage
    .from(BUCKET)
    .upload(path, file, { contentType: "application/pdf", upsert: false });
  if (up.error) throw up.error;
  const { error } = await supabase.from("trial_sources").insert({
    team_id: teamId,
    trial_id: trialId,
    kind,
    origin: "upload",
    storage_path: path,
    filename: file.name.slice(0, 200),
    media_type: "application/pdf",
    bytes: file.size,
    added_by: userId,
  });
  if (error) {
    await supabase.storage.from(BUCKET).remove([path]);
    throw error;
  }
}

export async function removeSource(s: TrialSource) {
  const { error } = await supabase.from("trial_sources").delete().eq("id", s.id);
  if (error) throw error;
  await supabase.storage.from(BUCKET).remove([s.storage_path]);
}

/** A short-lived link to open a source. */
export async function sourceUrl(s: TrialSource): Promise<string> {
  const { data, error } = await supabase.storage.from(BUCKET).createSignedUrl(s.storage_path, 300);
  if (error) throw error;
  return data.signedUrl;
}

// --- checking and correcting ------------------------------------------------------

export async function fetchReviews(teamId: string, trialId: string): Promise<Set<string>> {
  const { data, error } = await supabase
    .from("trial_fact_reviews")
    .select("path")
    .eq("team_id", teamId)
    .eq("trial_id", trialId);
  if (error) throw error;
  return new Set((data as { path: string }[]).map((r) => r.path));
}

export async function setVerified(
  teamId: string,
  trialId: string,
  userId: string,
  path: string,
  verified: boolean,
) {
  const { error } = verified
    ? await supabase
        .from("trial_fact_reviews")
        // Ignore a duplicate (someone verified it meanwhile): members may
        // insert reviews, not update them.
        .upsert(
          { team_id: teamId, trial_id: trialId, path, verified_by: userId },
          { onConflict: "team_id,trial_id,path", ignoreDuplicates: true },
        )
    : await supabase
        .from("trial_fact_reviews")
        .delete()
        .eq("team_id", teamId)
        .eq("trial_id", trialId)
        .eq("path", path);
  if (error) throw error;
}

/** Correct one value; the database logs it and clears its "verified". */
export async function editFact(teamId: string, trialId: string, path: string, value: unknown) {
  const { error } = await supabase.rpc("edit_trial_fact", {
    p_team: teamId,
    p_trial: trialId,
    p_path: path,
    p_value: value,
  });
  if (error) throw error;
}

export async function countEdits(teamId: string, trialId: string): Promise<number> {
  const { count, error } = await supabase
    .from("trial_fact_edits")
    .select("id", { count: "exact", head: true })
    .eq("team_id", teamId)
    .eq("trial_id", trialId);
  if (error) throw error;
  return count ?? 0;
}
