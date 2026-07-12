import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface MentionRow {
  id: string;
  created_at: string;
  seen_at: string | null;
  paper_id: string;
  papers: { id: string; title: string | null } | null;
}

/** Papers a teammate @-mentioned this user on, newest first. */
export function useMentions(userId: string) {
  return useQuery({
    queryKey: ["mentions", userId],
    queryFn: async (): Promise<MentionRow[]> => {
      const { data, error } = await supabase
        .from("mentions")
        .select("id, created_at, seen_at, paper_id, papers(id, title)")
        .eq("mentioned_user", userId)
        .order("created_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as unknown as MentionRow[];
    },
  });
}
