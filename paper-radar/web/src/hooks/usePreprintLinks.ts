import { useQuery } from "@tanstack/react-query";

import type { PreprintLink } from "@/lib/preprint";
import { supabase } from "@/lib/supabase";

/** The preprint version of each paper that has one, keyed by paper id. One
 *  `.in()` read over the loaded page, like useEngagementCounts. */
export function usePreprintLinks(paperIds: string[]) {
  const key = [...paperIds].sort().join(",");
  return useQuery({
    queryKey: ["preprint-links", key],
    enabled: paperIds.length > 0,
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<Record<string, PreprintLink>> => {
      const { data, error } = await supabase
        .from("paper_aliases")
        .select("paper_id, url, doi, venue, created_at")
        .eq("kind", "preprint")
        .in("paper_id", paperIds)
        .order("created_at");
      if (error) throw error;
      const map: Record<string, PreprintLink> = {};
      // The earliest recorded preprint wins: usually the one the lab posted.
      for (const r of data ?? []) map[r.paper_id] ??= { url: r.url, doi: r.doi, venue: r.venue };
      return map;
    },
  });
}

/** The paper an id was merged into (a preprint folded into its published
 *  version, or a duplicate), so an old link can redirect. Asked only once the
 *  id itself has come back empty. */
export function useMergedInto(paperId: string | null | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["merged-into", paperId],
    enabled: enabled && !!paperId,
    staleTime: Infinity,
    queryFn: async (): Promise<string | null> => {
      const { data, error } = await supabase
        .from("paper_aliases")
        .select("paper_id")
        .eq("old_paper_id", paperId!)
        .maybeSingle();
      if (error) throw error;
      return data?.paper_id ?? null;
    },
  });
}
