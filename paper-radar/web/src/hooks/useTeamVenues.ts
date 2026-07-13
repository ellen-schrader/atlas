import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface VenueCount {
  venue: string;
  count: number;
}

/** The venues a lab actually has, most common first — the options for the filter. */
export function useTeamVenues(teamId: string) {
  return useQuery({
    queryKey: ["team-venues", teamId],
    queryFn: async (): Promise<VenueCount[]> => {
      const { data, error } = await supabase.rpc("team_venues", { p_team: teamId });
      if (error) throw error;
      return (data ?? []) as VenueCount[];
    },
    staleTime: 5 * 60 * 1000,
  });
}
