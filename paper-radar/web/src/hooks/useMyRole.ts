import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

/** The current user's role in a lab ("owner" | "member" | null). */
export function useMyRole(teamId: string, userId: string) {
  return useQuery({
    queryKey: ["my-role", teamId, userId],
    queryFn: async (): Promise<string | null> => {
      const { data, error } = await supabase
        .from("team_members")
        .select("role")
        .eq("team_id", teamId)
        .eq("user_id", userId)
        .maybeSingle();
      if (error) throw error;
      return (data?.role as string | undefined) ?? null;
    },
  });
}
