import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

/** The features switched on for the current user in this lab (for the lab, or
 *  just for them). Empty while loading, so a dark feature never flashes in;
 *  `loaded` says whether an empty list is the answer yet. */
export function useFeatures(teamId: string): { features: string[]; loaded: boolean } {
  const { data, isError } = useQuery({
    queryKey: ["features", teamId],
    queryFn: async (): Promise<string[]> => {
      const { data, error } = await supabase.rpc("my_features", { t: teamId });
      if (error) throw error;
      return (data as string[] | null) ?? [];
    },
    staleTime: 5 * 60_000,
  });
  return { features: data ?? [], loaded: data !== undefined || isError };
}
