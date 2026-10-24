import { supabase } from "@/lib/supabase";
import type {
  SavedSearch,
  SearchFields,
  SourceKey,
  SourceResult,
  Suggestion,
} from "@/lib/savedSearches";
import type {
  MapDoc,
  MapOverviewData,
  MapPapersData,
  MapSummary,
  OverviewData,
  Recommendation,
  SemanticHit,
} from "@/lib/types";

export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

/** Error from the Atlas API. `status` is the HTTP code; undefined means the
 *  service was unreachable (network failure / CORS / machine cold-booting).
 *
 *  Retry/cold-boot policy for these errors lives in the QueryClient defaults
 *  (main.tsx) and applies to useQuery reads only — imperative callers get a
 *  single attempt and should surface the message themselves. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

/** Worth retrying: only the shapes a cold-booting machine produces —
 *  unreachable (fetch rejected) or the Fly proxy's 502/504. App-generated
 *  statuses are deterministic here: 4xx never heals, and the API uses 503
 *  ("Embeddings unavailable") and 500 as real answers from a running
 *  service, so retrying them just delays the truth. */
export function isTransientApiError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === undefined || error.status === 502 || error.status === 504)
  );
}

export interface PostResult {
  post_id: string;
  paper_id: string;
  already_posted: boolean;
  paper: { url: string; title: string | null };
}

/** The metadata fields a user can see and correct before a paper is added. */
export interface PaperFields {
  title: string | null;
  authors: string[];
  venue: string | null;
  year: number | null;
  doi: string | null;
  abstract: string | null;
  keywords: string[];
  /** "arxiv" | "crossref" | "pubmed" | "citation_meta" | "manual" | "unknown" */
  source: string;
}

/** A preprint whose published version Atlas stores instead. */
export interface ReplacedPreprint {
  doi: string | null;
  url: string | null;
  /** The server: "bioRxiv", "arXiv", … */
  venue: string | null;
  reason: "crossref" | "biorxiv" | "arxiv";
}

export interface ResolvedPaper extends PaperFields {
  url: string;
  /** Normalized dedup key — what `papers.url_norm` is matched on. */
  url_norm: string;
  /** Set when the pasted link was a preprint that has since been published: the
   *  rest of this record is then the published version, which is what gets added. */
  replaced_preprint?: ReplacedPreprint | null;
}

/** Look a URL up without writing anything: the autofill behind the Add-paper
 *  dialog. A bot-walled publisher resolves to a record with no title — that is
 *  an expected outcome, not an error, and the caller falls back to manual entry. */
export function resolvePaper(url: string): Promise<ResolvedPaper> {
  // Authenticated: /resolve makes the server fetch a URL you chose, so it isn't open
  // to the world any more.
  return authedRequest<ResolvedPaper>("/resolve", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

async function authToken(): Promise<string> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Not signed in.");
  return token;
}

/** Post a paper into a lab via the API (sends the user's Supabase JWT).
 *
 *  `fields` is the metadata the user approved in the Add-paper dialog. Sending it
 *  stops the server re-resolving the URL — which is what makes a hand-typed title
 *  survive for a bot-walled publisher that resolves to nothing. Omit it and the
 *  server resolves the URL itself, as it always did. */
export function postPaper(
  url: string,
  teamId: string,
  fields?: PaperFields,
  note?: string,
  replacedPreprint?: ReplacedPreprint | null,
): Promise<PostResult> {
  return authedRequest<PostResult>("/posts", {
    method: "POST",
    body: JSON.stringify({
      url,
      team_id: teamId,
      fields: fields ?? null,
      note: note?.trim() || null,
      replaced_preprint: replacedPreprint ?? null,
    }),
  });
}

/** What a person may correct on a paper. Not `doi` or `url`: those are dedup
 *  keys, and changing one is a merge, not an edit. */
export interface PaperCorrection {
  title?: string | null;
  authors?: string[];
  venue?: string | null;
  year?: number | null;
  abstract?: string | null;
  code_url?: string | null;
  data_url?: string | null;
}

export interface PaperEditResult {
  status: "updated" | "unchanged" | "unresolved";
  paper: Record<string, unknown>;
  /** Only set by POST /papers/{id}/resolve, which the web app does not call. */
  duplicate_of: string | null;
}

/** Correct a paper by hand, for every lab that holds it. `expectedEditedAt` is
 *  the paper's `edited_at` as the form was loaded; if it has moved since, this
 *  rejects with a 409 rather than silently overwriting someone else's fix. */
export function fixPaperMetadata(
  paperId: string,
  expectedEditedAt: string | null,
  fields: PaperCorrection,
): Promise<PaperEditResult> {
  return authedRequest<PaperEditResult>(`/papers/${encodeURIComponent(paperId)}`, {
    method: "PATCH",
    body: JSON.stringify({ expected_edited_at: expectedEditedAt, ...fields }),
  });
}

/** Call the Atlas API; throws the API's `detail` on error. */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    // fetch throws on network failure / CORS / service down — give the user
    // something actionable rather than the raw "Failed to fetch".
    throw new ApiError("Couldn’t reach the paper service. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = `Request failed (error ${res.status}).`;
    try {
      const body = (await res.json()).detail;
      // FastAPI's own validation errors are a list of {msg, ...}.
      detail = Array.isArray(body) ? (body[0]?.msg ?? detail) : (body ?? detail);
    } catch {
      // non-JSON error body
    }
    throw new ApiError(detail, res.status);
  }
  // 204 has no body to parse (e.g. POST /account/delete).
  return (res.status === 204 ? undefined : res.json()) as Promise<T>;
}

/** Call the Atlas API with the user's JWT; throws the API's detail on error. */
async function authedRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await authToken();
  return request<T>(path, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, ...init.headers },
  });
}

/** Rank the lab's papers against a free-text query by embedding similarity. */
export async function semanticSearch(
  query: string,
  teamId: string,
  limit = 30,
): Promise<SemanticHit[]> {
  const data = await authedRequest<{ results: SemanticHit[] }>("/search/semantic", {
    method: "POST",
    body: JSON.stringify({ query, team_id: teamId, limit }),
  });
  return data.results;
}

/** Insights overview: 2-D t-SNE layout + named clusters + stats for the lab. */
export function fetchOverview(teamId: string): Promise<OverviewData> {
  return authedRequest<OverviewData>(`/overview?team_id=${encodeURIComponent(teamId)}`);
}

// --- topic maps ------------------------------------------------------------

/** The lab's topic maps visible to the caller (RLS hides others' private maps). */
export function fetchMaps(teamId: string): Promise<MapDoc[]> {
  return authedRequest<MapDoc[]>(`/maps?team_id=${encodeURIComponent(teamId)}`);
}

/** Create a topic map; the seed phrase is embedded server-side for membership. */
export function createMap(teamId: string, name: string, seed: string): Promise<MapDoc> {
  return authedRequest<MapDoc>("/maps", {
    method: "POST",
    body: JSON.stringify({ team_id: teamId, name, seed }),
  });
}

/** Delete a map (creator only; a 404 means it wasn't yours). */
export function deleteMap(mapId: string): Promise<{ deleted: boolean }> {
  return authedRequest(`/maps/${encodeURIComponent(mapId)}`, { method: "DELETE" });
}

/** One curation/edit action on a map (creator only): rename, re-seed, change
 *  visibility, tune the match threshold, or pin/exclude a paper. */
export interface MapPatch {
  name?: string;
  seed?: string;
  visibility?: "lab" | "private";
  min_similarity?: number;
  pin?: string;
  unpin?: string;
  exclude?: string;
  uninclude?: string;
  clear_excluded?: boolean;
}
export function updateMap(mapId: string, patch: MapPatch): Promise<MapDoc> {
  return authedRequest<MapDoc>(`/maps/${encodeURIComponent(mapId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

/** A map's scoped overview: t-SNE + sub-themes over just its member papers. */
export function fetchMapOverview(mapId: string): Promise<MapOverviewData> {
  return authedRequest<MapOverviewData>(`/maps/${encodeURIComponent(mapId)}/overview`);
}

/** A map's member papers, ranked, with the caller's read-state + relevance, and
 *  the labs driving the topic. sort: "importance" | "recent" | "discussed". */
export function fetchMapPapers(mapId: string, sort: string): Promise<MapPapersData> {
  const p = encodeURIComponent(mapId);
  return authedRequest<MapPapersData>(`/maps/${p}/papers?sort=${encodeURIComponent(sort)}`);
}

/** The cached AI summary of a map (text is empty when none has been generated). */
export function fetchMapSummary(mapId: string): Promise<MapSummary> {
  return authedRequest<MapSummary>(`/maps/${encodeURIComponent(mapId)}/summary`);
}

/** Generate (and cache) the map's summary — on demand, since it costs a model call.
 *  force=true so an explicit "Regenerate" re-runs the model instead of returning the
 *  cached summary (the endpoint serves the cache to an un-forced POST). */
export function generateMapSummary(mapId: string): Promise<MapSummary> {
  return authedRequest<MapSummary>(`/maps/${encodeURIComponent(mapId)}/summary?force=true`, {
    method: "POST",
  });
}

/** Cosine similarity of every embedded paper in the lab to a query (for the
 *  map's Relevance color mode). Returns { paper_id: similarity }. */
export async function fetchSimilarity(
  query: string,
  teamId: string,
): Promise<Record<string, number>> {
  const data = await authedRequest<{ similarities: Record<string, number> }>("/similarity", {
    method: "POST",
    body: JSON.stringify({ query, team_id: teamId }),
  });
  return data.similarities;
}

export type RecScope = "discover" | "reading_list";

export interface RecommendationsResult {
  results: Recommendation[];
  cold_start: boolean; // true = no taste signal yet (recency fallback used)
}

/** Personalized papers for the user in a lab, ranked by their taste vector.
 *  scope="discover" = unseen papers; scope="reading_list" = saved papers ranked. */
export function fetchRecommendations(
  teamId: string,
  scope: RecScope = "discover",
  limit = 12,
): Promise<RecommendationsResult> {
  const q = new URLSearchParams({ team_id: teamId, scope, limit: String(limit) });
  return authedRequest<RecommendationsResult>(`/recommendations?${q}`);
}

/** Save the user's research profile description and re-embed it (personalises
 *  recommendations). Returns whether the embedding was (re)computed. */
export function updateProfile(profileMd: string): Promise<{ ok: boolean; embedded: boolean }> {
  return authedRequest("/profile", {
    method: "POST",
    body: JSON.stringify({ profile_md: profileMd }),
  });
}

/** Delete the caller's account (POST /account/delete). Throws the API's message
 *  when refused: a mistyped email, or being the last owner of a lab with others. */
export function deleteAccount(confirmEmail: string): Promise<void> {
  return authedRequest("/account/delete", {
    method: "POST",
    body: JSON.stringify({ confirm_email: confirmEmail }),
  });
}

// --- BibTeX import ---------------------------------------------------------

export interface BibEntryPreview {
  key: string;
  title: string | null;
  authors: string[];
  venue: string | null;
  year: number | null;
  published_at: string | null;
  doi: string | null;
  url: string | null;
  /** "new" | "duplicate" | "no_doi" | "rejected" */
  status: string;
  reason: string | null;
}

export interface PreflightResult {
  entries: BibEntryPreview[];
  new: number;
  duplicates: number;
  no_doi: number;
  rejected: number;
  /** What Import will actually add: new + no_doi. "No DOI" is a warning, not a refusal. */
  importable: number;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  failed: number;
}

/** What the file *would* do. Writes nothing — the user sees it before committing. */
export function bibtexPreflight(bibtex: string, teamId: string): Promise<PreflightResult> {
  return authedRequest<PreflightResult>("/import/bibtex/preflight", {
    method: "POST",
    body: JSON.stringify({ team_id: teamId, bibtex }),
  });
}

export function bibtexImport(bibtex: string, teamId: string): Promise<ImportResult> {
  return authedRequest<ImportResult>("/import/bibtex", {
    method: "POST",
    body: JSON.stringify({ team_id: teamId, bibtex }),
  });
}

// --- Teams integration -------------------------------------------------------

export interface TeamsIntegration {
  configured: boolean;
  /** The webhook host only — the full URL is a bearer secret and never leaves the server. */
  host: string | null;
  enabled: boolean;
  /** Whether inbound (@Atlas → Atlas) is set up. The token itself never leaves the server. */
  inbound_configured: boolean;
  updated_at: string | null;
}

/** The public URL a lab pastes into its Teams Outgoing Webhook so `@Atlas <link>`
 *  reaches this API. The team id is not a secret — the HMAC token is the gate. */
export function teamsInboundUrl(teamId: string): string {
  return `${API_URL}/integrations/teams/inbound/${encodeURIComponent(teamId)}`;
}

/** The lab's Teams connection (host + status). RLS-scoped: non-owners see "not configured". */
export function getTeamsIntegration(teamId: string): Promise<TeamsIntegration> {
  return authedRequest<TeamsIntegration>(
    `/integrations/teams?team_id=${encodeURIComponent(teamId)}`,
  );
}

/** Connect (or replace) the lab's Teams webhook. The server validates the URL
 *  against the Power Automate host allowlist and rejects anything else. */
export function saveTeamsIntegration(
  teamId: string,
  webhookUrl: string,
  enabled = true,
): Promise<TeamsIntegration> {
  return authedRequest<TeamsIntegration>("/integrations/teams", {
    method: "PUT",
    body: JSON.stringify({ team_id: teamId, webhook_url: webhookUrl, enabled }),
  });
}

/** Pause/resume without moving the secret — flips `enabled` on the stored row. */
export function setTeamsEnabled(teamId: string, enabled: boolean): Promise<TeamsIntegration> {
  return authedRequest<TeamsIntegration>("/integrations/teams", {
    method: "PATCH",
    body: JSON.stringify({ team_id: teamId, enabled }),
  });
}

export function deleteTeamsIntegration(teamId: string): Promise<TeamsIntegration> {
  return authedRequest<TeamsIntegration>(
    `/integrations/teams?team_id=${encodeURIComponent(teamId)}`,
    { method: "DELETE" },
  );
}

/** Fire a sample card through the saved webhook so the owner sees it working. */
export function testTeamsIntegration(teamId: string): Promise<{ ok: boolean }> {
  return authedRequest<{ ok: boolean }>("/integrations/teams/test", {
    method: "POST",
    body: JSON.stringify({ team_id: teamId }),
  });
}

/** Store the inbound (Outgoing Webhook) HMAC token so `@Atlas <link>` imports
 *  papers. Write-only — the token is validated as base64 and never returned. */
export function saveTeamsInboundSecret(teamId: string, secret: string): Promise<TeamsIntegration> {
  return authedRequest<TeamsIntegration>("/integrations/teams/inbound", {
    method: "PUT",
    body: JSON.stringify({ team_id: teamId, secret }),
  });
}

/** Turn off inbound ingestion by clearing the stored token. */
export function deleteTeamsInboundSecret(teamId: string): Promise<TeamsIntegration> {
  return authedRequest<TeamsIntegration>(
    `/integrations/teams/inbound?team_id=${encodeURIComponent(teamId)}`,
    { method: "DELETE" },
  );
}

// --- clinical trials (dark unless the feature is on; see lib/trials.ts) -------

export interface TrialHit {
  nct_id: string;
  title: string;
  acronym: string | null;
  phases: string[];
  status: string | null;
  conditions: string[];
  in_lab: boolean;
}

/** Breast cancer trials on ClinicalTrials.gov matching an NCT ID, a trial name
 *  or free text. */
export async function searchTrials(teamId: string, q: string): Promise<TrialHit[]> {
  const params = new URLSearchParams({ team_id: teamId, q });
  return authedRequest<TrialHit[]>(`/trials/search?${params}`);
}

/** Add a trial to the lab by NCT ID. */
export async function addTrial(
  teamId: string,
  nctId: string,
): Promise<{ trial: { id: string; nct_id: string }; already_in_lab: boolean }> {
  return authedRequest("/trials", {
    method: "POST",
    body: JSON.stringify({ team_id: teamId, nct_id: nctId }),
  });
}

/** Fetch open-access full text of the trial's linked papers (Europe PMC). */
export async function fetchOpenAccess(
  teamId: string,
  trialId: string,
): Promise<{ fetched: string[]; closed: string[]; have: string[]; unconfirmed?: string[] }> {
  return authedRequest(`/trials/${trialId}/open-access`, {
    method: "POST",
    body: JSON.stringify({ team_id: teamId }),
  });
}

/** One cell of a table in a full-text source, with its spans. */
export interface CitedCell {
  text: string;
  header: boolean;
  colspan: number;
  rowspan: number;
}

/** A table, figure or section of a full-text source, ready to show. */
export interface CitedElement {
  id: string;
  kind: "table" | "figure" | "section";
  label: string;
  caption: string;
  rows: CitedCell[][];
  /** A section's text; "## " starts a subheading. */
  paragraphs: string[];
  footnotes: string[];
  /** A figure's image on PMC (served from NCBI's image host). */
  image: string | null;
}

/** Where a source's quote is in an element: a table row, footnote,
 *  paragraph or caption by index ("heading": the label and caption read
 *  together), and the characters it covers there. */
export interface QuoteHit {
  where: "row" | "footnote" | "paragraph" | "caption" | "heading";
  index: number;
  start: number;
  end: number;
}

/** One part of an extracted value's source ("Table 1 (ECOG PS)"), and what
 *  it points at (null when nothing in the article matched). */
export interface CitedPart {
  part: string;
  element: CitedElement | null;
  /** The table rows the part names. */
  rows: number[];
  /** The figure panel the part names ("d"). */
  panel: string | null;
  /** Where the source's quote is in this part's element. */
  quote: QuoteHit | null;
  /** Not a place the source named: where its quote turned up instead. */
  elsewhere: boolean;
}

/** What a source's "where" (and anchor) point at in one of the trial's
 *  full-text files, where its quote is (quote_found null: it has none), and
 *  the article on PMC (each element's id is its anchor there). */
export async function fetchCited(
  teamId: string,
  trialId: string,
  sourceId: string,
  where: string,
  anchor?: string | null,
  quote?: string | null,
): Promise<{ parts: CitedPart[]; article_url: string | null; quote_found: boolean | null }> {
  const q = new URLSearchParams({ team_id: teamId, where });
  if (anchor) q.set("anchor", anchor);
  if (quote) q.set("quote", quote);
  return authedRequest(`/trials/${trialId}/sources/${sourceId}/cited?${q}`);
}

/** Start Claude's extraction of the trial's data from its sources: queued for
 *  the next batch (half price, within hours) or now (full price). */
export async function startExtraction(
  teamId: string,
  trialId: string,
  mode: "batch" | "now" = "batch",
): Promise<void> {
  await authedRequest(`/trials/${trialId}/extract`, {
    method: "POST",
    body: JSON.stringify({ team_id: teamId, mode }),
  });
}

/** At most this many trials per getTrialsData request (api/trial_extract.py). */
export const MAX_GET_DATA = 30;

/** Get data for several trials in one request (a collection's "Get data"):
 *  the server fetches open-access full text for those with no files and
 *  queues them for the next batch. Trials with data are left alone. */
export async function getTrialsData(
  teamId: string,
  trialIds: string[],
): Promise<{ queued: string[]; need_pdf: string[]; unconfirmed?: string[]; skipped: string[] }> {
  return authedRequest("/trials/get-data", {
    method: "POST",
    body: JSON.stringify({ team_id: teamId, trial_ids: trialIds }),
  });
}

/** This month's extraction spend for the lab, and its cap. */
export async function fetchExtractionBudget(
  teamId: string,
): Promise<{ spent_usd: number; cap_usd: number }> {
  return authedRequest(`/trials/budget?${new URLSearchParams({ team_id: teamId })}`);
}

export interface PubMedHint {
  count: number;
  /** How many of `count` were compared with the library (the most recent). */
  checked: number;
  not_in_lab: { pmid: string; title: string; journal: string | null; year: string | null; doi: string | null }[];
  search_url: string;
}

/** PubMed papers naming this trial, and which the lab doesn't have. */
export async function fetchPubMedHint(teamId: string, trialId: string): Promise<PubMedHint> {
  return authedRequest(`/trials/${trialId}/pubmed?${new URLSearchParams({ team_id: teamId })}`);
}

// --- Saved searches (issue #164) -------------------------------------------------

export async function listSearches(teamId: string): Promise<SavedSearch[]> {
  return authedRequest(`/saved-searches?${new URLSearchParams({ team_id: teamId })}`);
}

export async function createSearch(teamId: string, fields: SearchFields): Promise<SavedSearch> {
  return authedRequest("/saved-searches", {
    method: "POST",
    body: JSON.stringify({ team_id: teamId, ...fields }),
  });
}

export async function updateSearch(
  teamId: string,
  id: string,
  fields: Partial<SearchFields> & { active?: boolean },
): Promise<SavedSearch> {
  return authedRequest(`/saved-searches/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ team_id: teamId, ...fields }),
  });
}

export async function deleteSearch(teamId: string, id: string): Promise<void> {
  return authedRequest(
    `/saved-searches/${encodeURIComponent(id)}?${new URLSearchParams({ team_id: teamId })}`,
    { method: "DELETE" },
  );
}

/** What the query finds over the past week, per source, without saving it. */
export async function previewSearch(
  teamId: string,
  query: string,
  sources: SourceKey[],
): Promise<SourceResult[]> {
  return authedRequest("/saved-searches/preview", {
    method: "POST",
    body: JSON.stringify({ team_id: teamId, query, sources }),
  });
}

export async function listSuggestions(teamId: string): Promise<Suggestion[]> {
  return authedRequest(`/saved-searches/suggestions?${new URLSearchParams({ team_id: teamId })}`);
}

/** The API takes at most this many ids per call. */
export const MAX_PER_CALL = 50;

/** Import or dismiss suggestions; returns how many were still waiting. */
export async function decideSuggestions(
  teamId: string,
  ids: string[],
  decision: "import" | "dismiss",
): Promise<number> {
  let count = 0;
  for (let i = 0; i < ids.length; i += MAX_PER_CALL) {
    const out = await authedRequest<{ count: number }>(`/saved-searches/suggestions/${decision}`, {
      method: "POST",
      body: JSON.stringify({ team_id: teamId, ids: ids.slice(i, i + MAX_PER_CALL) }),
    });
    count += out.count;
  }
  return count;
}
