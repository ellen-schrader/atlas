import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";
import type { Membership } from "@/lib/types";

/** Labs the current user belongs to (RLS returns only their own memberships). */
export function useMemberships(enabled: boolean) {
  return useQuery({
    queryKey: ["memberships"],
    enabled,
    queryFn: async (): Promise<Membership[]> => {
      const { data, error } = await supabase.from("team_members").select("role, teams(*)");
      if (error) throw error;
      return (data ?? []) as unknown as Membership[];
    },
  });
}
