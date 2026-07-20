import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface ReadingRow {
  paper_id: string;
  updated_at: string;
  papers: {
    id: string;
    title: string | null;
    venue: string | null;
    year: number | null;
    authors: string[] | null;
    // Fetched so the list can be exported (BibTeX, links, optional abstracts).
    doi: string | null;
    url: string | null;
    abstract: string | null;
  } | null;
}

/** The user's "to read" list in a lab, newest first. */
export function useReadingList(userId: string, teamId: string) {
  return useQuery({
    queryKey: ["reading-list", userId, teamId],
    queryFn: async (): Promise<ReadingRow[]> => {
      const { data, error } = await supabase
        .from("paper_status")
        .select("paper_id, updated_at, papers(id, title, venue, year, authors, doi, url, abstract)")
        .eq("user_id", userId)
        .eq("team_id", teamId)
        .eq("status", "to_read")
        .order("updated_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as unknown as ReadingRow[];
    },
  });
}

/** How many papers the user has marked read in this lab in the last 7 days — the
 *  reading list's momentum signal. `updated_at` is stamped when status flips to
 *  "read", so a recent read shows up here. */
export function useReadThisWeek(userId: string, teamId: string) {
  return useQuery({
    queryKey: ["read-this-week", userId, teamId],
    queryFn: async (): Promise<number> => {
      const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
      const { count, error } = await supabase
        .from("paper_status")
        .select("paper_id", { count: "exact", head: true })
        .eq("user_id", userId)
        .eq("team_id", teamId)
        .eq("status", "read")
        .gte("updated_at", weekAgo);
      if (error) throw error;
      return count ?? 0;
    },
  });
}
