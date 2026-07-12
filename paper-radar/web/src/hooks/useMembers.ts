import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface Member {
  user_id: string;
  role: "owner" | "member";
  // profile_md backs the hover summary on an @mention.
  profiles: { display_name: string; profile_md: string } | null;
}

/** The lab's members with their roles and research profiles. */
export function useMembers(teamId: string) {
  return useQuery({
    queryKey: ["members", teamId],
    queryFn: async (): Promise<Member[]> => {
      const { data, error } = await supabase
        .from("team_members")
        .select("user_id, role, profiles(display_name, profile_md)")
        .eq("team_id", teamId)
        .order("role");
      if (error) throw error;
      return (data ?? []) as unknown as Member[];
    },
  });
}
