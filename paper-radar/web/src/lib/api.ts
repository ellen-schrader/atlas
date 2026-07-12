import { supabase } from "@/lib/supabase";

export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export interface PostResult {
  post_id: string;
  paper_id: string;
  already_posted: boolean;
  paper: { url: string; title: string | null };
}

/** Post a paper into a lab via the API (sends the user's Supabase JWT). */
export async function postPaper(url: string, teamId: string): Promise<PostResult> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Not signed in.");

  const res = await fetch(`${API_URL}/posts`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ url, team_id: teamId }),
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
