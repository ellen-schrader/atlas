import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";

/** Papers posted in a lab, newest first (RLS returns only the caller's labs). */
export function usePapers(teamId: string) {
  return useQuery({
    queryKey: ["papers", teamId],
    queryFn: async (): Promise<PaperPost[]> => {
      const { data, error } = await supabase
        .from("paper_posts")
        .select("id, posted_at, note, posted_by, posted_by_label, tags, papers(*)")
        .eq("team_id", teamId)
        .order("posted_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as unknown as PaperPost[];
    },
  });
}
