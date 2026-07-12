import { supabase } from "@/lib/supabase";
import type { OverviewData, SemanticHit } from "@/lib/types";

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
