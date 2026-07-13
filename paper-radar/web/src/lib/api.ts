import { supabase } from "@/lib/supabase";
import type { OverviewData, Recommendation, SemanticHit } from "@/lib/types";

export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export interface PostResult {
  post_id: string;
  paper_id: string;
  already_posted: boolean;
  paper: { url: string; title: string | null };
}

async function authToken(): Promise<string> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Not signed in.");
  return token;
}

/** Post a paper into a lab via the API (sends the user's Supabase JWT). */
export async function postPaper(url: string, teamId: string): Promise<PostResult> {
  const token = await authToken();

  let res: Response;
  try {
    res = await fetch(`${API_URL}/posts`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ url, team_id: teamId }),
    });
  } catch {
    // fetch throws on network failure / CORS / service down — give the user
    // something actionable rather than the raw "Failed to fetch".
    throw new Error("Couldn’t reach the paper service. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = `Couldn’t post that paper (error ${res.status}).`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(detail);
  }
  return res.json();
}

/** Call the Atlas API with the user's JWT; throws the API's detail on error. */
async function authedRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await authToken();
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...init.headers,
      },
    });
  } catch {
    throw new Error("Couldn’t reach the paper service. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = `Request failed (error ${res.status}).`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(detail);
  }
  return res.json();
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

/** Insights overview: UMAP layout + named clusters + stats for the lab. */
export function fetchOverview(teamId: string): Promise<OverviewData> {
  return authedRequest<OverviewData>(`/overview?team_id=${encodeURIComponent(teamId)}`);
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
