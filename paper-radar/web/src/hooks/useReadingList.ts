import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface ReadingRow {
  paper_id: string;
  updated_at: string;
  papers: { id: string; title: string | null; venue: string | null; year: number | null } | null;
}

/** The user's "to read" list in a lab, newest first. */
export function useReadingList(userId: string, teamId: string) {
  return useQuery({
    queryKey: ["reading-list", userId, teamId],
    queryFn: async (): Promise<ReadingRow[]> => {
      const { data, error } = await supabase
        .from("paper_status")
        .select("paper_id, updated_at, papers(id, title, venue, year)")
        .eq("user_id", userId)
        .eq("team_id", teamId)
        .eq("status", "to_read")
        .order("updated_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as unknown as ReadingRow[];
    },
  });
}
