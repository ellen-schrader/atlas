import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";
import type { Membership } from "@/lib/types";

/** Labs the current user belongs to. */
export function useMemberships(enabled: boolean, userId: string | undefined) {
  return useQuery({
    queryKey: ["memberships", userId],
    enabled: enabled && !!userId,
    queryFn: async (): Promise<Membership[]> => {
      // RLS lets a member see co-members' rows too, so filter to our own and give
      // them a stable order. Without this, teams[0] (the active lab) is drawn from
      // an unordered set and can be a co-member's row or flip between refetches for
      // a user in more than one lab — the app would read/write the wrong lab.
      const { data, error } = await supabase
        .from("team_members")
        .select("role, teams(*)")
        .eq("user_id", userId!)
        .order("joined_at", { ascending: true });
      if (error) throw error;
      return (data ?? []) as unknown as Membership[];
    },
  });
}
