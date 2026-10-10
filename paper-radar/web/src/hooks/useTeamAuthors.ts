import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface AuthorCount {
  author: string;
  n: number;
}

/** Every author on a lab's papers, most papers first — the options for the
 *  author filter (team_authors RPC). Names are matched exactly as stored. */
export function useTeamAuthors(teamId: string) {
  return useQuery({
    queryKey: ["team-authors", teamId],
    queryFn: async (): Promise<AuthorCount[]> => {
      const { data, error } = await supabase.rpc("team_authors", { p_team: teamId });
      if (error) throw error;
      return (data ?? []) as AuthorCount[];
    },
    staleTime: 5 * 60 * 1000,
  });
}
