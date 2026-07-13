import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

/** The venues a lab actually has, most common first — the options for the filter. */
export function useTeamVenues(teamId: string) {
  return useQuery({
    queryKey: ["team-venues", teamId],
    queryFn: async (): Promise<{ venue: string; count: number }[]> => {
      const { data, error } = await supabase.rpc("team_venues", { p_team: teamId });
      if (error) throw error;
      return (data ?? []) as { venue: string; count: number }[];
    },
    staleTime: 5 * 60 * 1000,
  });
}
