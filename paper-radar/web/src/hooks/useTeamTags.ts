import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface TagCount {
  tag: string;
  n: number;
}

/** Distinct lab-applied tags with counts, for the filter chips (team_tags RPC).
 *  Server-side because paginated results no longer hold the whole collection. */
export function useTeamTags(teamId: string) {
  return useQuery({
    queryKey: ["team-tags", teamId],
    queryFn: async (): Promise<TagCount[]> => {
      const { data, error } = await supabase.rpc("team_tags", { p_team: teamId });
      if (error) throw error;
      return (data ?? []) as TagCount[];
    },
  });
}
