import { supabase } from "@/lib/supabase";

/** What Claude extracted from a trial's papers (trial_facts.extraction).
 *  Mirrors paper_radar/trials/extraction.py. */

export interface Source {
  doc: number;
  where: string;
  page: string | null;
  /** In a full text: the id of the table, figure or section ("Tab1"). Older
   *  extractions don't have it. */
  anchor?: string | null;
  /** A few words copied from there that show the main value. */
  quote?: string | null;
}

/** Finds a source's quote in the paper's text however its spacing or table
 *  cell breaks fall: words in order, separated by spaces or " | ". */
export function quoteMatcher(quote: string | null | undefined): RegExp | null {
  const words = (quote ?? "").replace(/[|…]/g, " ").split(/\s+/).filter(Boolean);
  if (words.length === 0) return null;
  const esc = (w: string) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(words.map(esc).join("[\\s|]+"), "i");
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

/** The categories of each baseline dimension (paper_radar/trials/extraction.py). */
export const DIMENSION_CATEGORIES: Record<string, string[]> = {
  t_stage: ["T1", "T2", "T3", "T4"],
  nodal_status: ["N0", "N1", "N2–3"],
  overall_stage: ["I", "II", "III"],
  ecog: ["0", "1", "2+"],
  tils: ["High", "Int", "Low"],
  age: ["<40", "40–49", "50–64", "≥65"],
  pdl1: ["Positive", "Negative"],
  menopausal_status: ["Pre", "Post"],
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
/** PDFs travel base64-encoded in a 32 MB request: 24 MB is the most one can be. */
export const MAX_UPLOAD_BYTES = 24 * 1024 * 1024;

/** What one trial's batch extraction costs, for the estimate before asking:
 *  measured at $0.13 a trial in October 2026 (papers plus supplements). */
export const EST_BATCH_USD = 0.13;

// A word that starts a dose or schedule: "125", "1200mg", "mg/m²", "AUC5",
// "q3w", "×4", "weekly". Only these end a name, so "anti-HER2", "T-DM1" and
// "(dual HER2 blockade)" are kept whole.
const DOSE_WORD =
  /^(\d+([.,]\d+)?(mg|g|µg|mcg|iu|%)?$|(mg|µg|mcg|g|iu)(\/(m²|m2|kg))?$|auc\d|q\d+[wdh]?$|[×x]\d+$|weekly|daily|biweekly|every)/i;

/** A treatment's name without its dose and schedule, for a label too narrow
 *  for the whole thing: "Dose-dense doxorubicin 60 mg/m² + cyclophosphamide
 *  600 mg/m² q2w ×4" → "Dose-dense doxorubicin + cyclophosphamide". Combined
 *  ("+") and sequential ("then") parts are shortened one by one; text with no
 *  dose in it comes back as it was. */
export function treatmentName(label: string): string {
  const shorten = (part: string) => {
    const words = part.trim().split(/\s+/);
    // A dose follows a name: one in first place ("Cycles 1–4: …") isn't one.
    const dose = words.findIndex((w, i) => i > 0 && DOSE_WORD.test(w));
    // Never cut inside brackets: keep the name whole instead.
    const kept = dose > 0 ? words.slice(0, dose).join(" ") : part.trim();
    const open = (kept.match(/\(/g) ?? []).length;
    const close = (kept.match(/\)/g) ?? []).length;
    return open === close ? kept : part.trim();
  };
  return label
    .split(/\s+then\s+/i)
    .map((seq) => seq.split(/\s+\+\s+/).map(shorten).join(" + "))
    .join(" then ");
}

/** Where a trial's latest extraction stands. "stalled": it said running but
 *  went quiet past 30 minutes (a deploy, a crash) and can be started again. */
export type ExtractionState = "none" | "queued" | "batched" | "running" | "stalled" | "failed" | "done";

export function extractionState(
  f: {
    extraction_status: string | null;
    extraction_started_at: string | null;
    extracted_at: string | null;
  } | null,
): ExtractionState {
  const s = f?.extraction_status ?? null;
  if (s === "queued" || s === "batched" || s === "failed") return s;
  if (s === "running") return extractionRunning(s, f?.extraction_started_at ?? null) ? "running" : "stalled";
  return f?.extracted_at ? "done" : "none";
}

/** On its way: nothing to do but wait (and nothing to start again). */
export const inFlight = (state: ExtractionState) =>
  state === "queued" || state === "batched" || state === "running";

/** A run is "running" for 30 minutes at most: past that it crashed (a deploy,
 *  a restart), and the API lets a new one start. Mirrors api/trial_extract.py. */
export function extractionRunning(status: string | null, startedAt: string | null): boolean {
  return (
    status === "running" && !!startedAt && Date.now() - new Date(startedAt).getTime() < 30 * 60_000
  );
}

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
  /** The lab paper this PDF is, so open access doesn't fetch it again. */
  paperId: string | null,
) {
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf"))
    throw new Error("Only PDFs can be added.");
  if (file.size > MAX_UPLOAD_BYTES) throw new Error("That PDF is over 24 MB, too large to read.");
  const path = `${teamId}/${trialId}/${crypto.randomUUID()}.pdf`;
  const up = await supabase.storage
    .from(BUCKET)
    .upload(path, file, { contentType: "application/pdf", upsert: false });
  if (up.error) throw up.error;
  const { error } = await supabase.from("trial_sources").insert({
    team_id: teamId,
    trial_id: trialId,
    kind,
    paper_id: paperId,
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

/** The PMC page of a full text fetched from Europe PMC (stored as
 *  "<team>/<trial>/PMC123.xml"): readable, where the stored XML isn't. */
export function pmcUrl(s: Pick<TrialSource, "origin" | "storage_path">): string | null {
  const m = s.origin === "europepmc" ? /\/(PMC\d{1,10})\.xml$/.exec(s.storage_path) : null;
  return m ? `https://pmc.ncbi.nlm.nih.gov/articles/${m[1]}/` : null;
}

/** The first page a source names ("5", "p. 5–6", "S3" → 5, 5, 3), for
 *  opening a PDF there. */
export function firstPage(page: string | null): number | null {
  const m = page ? /\d+/.exec(page) : null;
  const n = m ? Number(m[0]) : 0;
  return n > 0 ? n : null;
}

/** Opens a trial's file where a source points: a PDF at its page, a Europe
 *  PMC full text on PMC (the stored XML isn't readable), anything else as is. */
export async function openSourceFile(s: TrialSource, page: string | null = null): Promise<void> {
  const n = s.media_type === "application/pdf" ? firstPage(page) : null;
  const url = pmcUrl(s) ?? (await sourceUrl(s)) + (n ? `#page=${n}` : "");
  window.open(url, "_blank", "noopener");
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

/** How many values the lab has corrected in the current extraction. */
export async function countEdits(
  teamId: string,
  trialId: string,
  since: string | null,
): Promise<number> {
  let q = supabase
    .from("trial_fact_edits")
    .select("path")
    .eq("team_id", teamId)
    .eq("trial_id", trialId);
  if (since) q = q.gte("edited_at", since);
  const { data, error } = await q;
  if (error) throw error;
  return new Set((data as { path: string }[]).map((r) => r.path)).size;
}
