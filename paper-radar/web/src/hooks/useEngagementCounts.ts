import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface Counts {
  reactions: number;
  comments: number;
}

/** Reaction + comment counts for a set of papers in a lab, for card/row
 *  engagement summaries. Two team-scoped `.in()` reads over the loaded page,
 *  counted client-side — cheap at a page's worth of ids, and no new RPC.
 *  (Folding these into search_papers is a later optimization.) */
export function useEngagementCounts(teamId: string, paperIds: string[]) {
  const key = [...paperIds].sort().join(",");
  return useQuery({
    queryKey: ["engagement-counts", teamId, key],
    enabled: paperIds.length > 0,
    queryFn: async (): Promise<Record<string, Counts>> => {
      const [rx, cm] = await Promise.all([
        supabase.from("reactions").select("paper_id").eq("team_id", teamId).in("paper_id", paperIds),
        supabase.from("comments").select("paper_id").eq("team_id", teamId).in("paper_id", paperIds),
      ]);
      if (rx.error) throw rx.error;
      if (cm.error) throw cm.error;

      const map: Record<string, Counts> = {};
      for (const id of paperIds) map[id] = { reactions: 0, comments: 0 };
      for (const r of rx.data ?? []) map[r.paper_id] && map[r.paper_id].reactions++;
      for (const c of cm.data ?? []) map[c.paper_id] && map[c.paper_id].comments++;
      return map;
    },
  });
}
