import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface Member {
  user_id: string;
  role: "owner" | "member";
  profiles: { display_name: string } | null;
}

/** The lab's members with their roles. */
export function useMembers(teamId: string) {
  return useQuery({
    queryKey: ["members", teamId],
    queryFn: async (): Promise<Member[]> => {
      const { data, error } = await supabase
        .from("team_members")
        .select("user_id, role, profiles(display_name)")
        .eq("team_id", teamId)
        .order("role");
      if (error) throw error;
      return (data ?? []) as unknown as Member[];
    },
  });
}
