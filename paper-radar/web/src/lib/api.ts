import { supabase } from "@/lib/supabase";
import type { MapData, SemanticHit } from "@/lib/types";

export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export interface PostResult {
  post_id: string;
  paper_id: string;
  already_posted: boolean;
  paper: { url: string; title: string | null };
}

/** Call the Atlas API with the user's Supabase JWT; throws with the API's detail on error. */
async function authedRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Not signed in.");

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(detail);
  }
  return res.json();
}

/** Post a paper into a lab via the API. */
export function postPaper(url: string, teamId: string): Promise<PostResult> {
  return authedRequest<PostResult>("/posts", {
    method: "POST",
    body: JSON.stringify({ url, team_id: teamId }),
  });
}

/** Rank the lab's posts against a free-text query by embedding similarity. */
export async function semanticSearch(
  query: string,
  teamId: string,
  limit = 20,
): Promise<SemanticHit[]> {
  const data = await authedRequest<{ results: SemanticHit[] }>("/search/semantic", {
    method: "POST",
    body: JSON.stringify({ query, team_id: teamId, limit }),
  });
  return data.results;
}

/** 2-D UMAP layout of the lab's embedded papers. */
export function fetchMap(teamId: string): Promise<MapData> {
  return authedRequest<MapData>(`/map?team_id=${encodeURIComponent(teamId)}`);
}
