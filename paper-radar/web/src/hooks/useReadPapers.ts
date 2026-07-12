import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

/** The set of paper ids the user has already read (or is reading) in a lab —
 *  powers the unread dot in list views. Personal, RLS-scoped. Invalidated under
 *  the `["read-papers"]` key wherever a paper is marked read. */
export function useReadPapers(userId: string, teamId: string) {
  return useQuery({
    queryKey: ["read-papers", userId, teamId],
    queryFn: async (): Promise<Set<string>> => {
      const { data, error } = await supabase
        .from("paper_status")
        .select("paper_id")
        .eq("user_id", userId)
        .eq("team_id", teamId)
        .in("status", ["read", "reading"]);
      if (error) throw error;
      return new Set((data ?? []).map((r) => r.paper_id as string));
    },
  });
}
