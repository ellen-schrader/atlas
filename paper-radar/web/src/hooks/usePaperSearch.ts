import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";

export const PAGE_SIZE = 30;

/** Server-side, paginated full-text search over a lab's papers (search_papers
 *  RPC). Embeds the joined paper so the result reuses the PaperPost shape. */
export function usePaperSearch(teamId: string, q: string, tag: string | null) {
  return useInfiniteQuery({
    queryKey: ["paper-search", teamId, q, tag],
    initialPageParam: 0,
    queryFn: async ({ pageParam }): Promise<PaperPost[]> => {
      const { data, error } = await supabase
        .rpc("search_papers", {
          p_team: teamId,
          p_q: q,
          p_tag: tag,
          p_limit: PAGE_SIZE,
          p_offset: pageParam,
        })
        .select("id, posted_at, note, posted_by, posted_by_label, tags, papers(*)");
      if (error) throw error;
      return (data ?? []) as unknown as PaperPost[];
    },
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length < PAGE_SIZE ? undefined : allPages.length * PAGE_SIZE,
  });
}

/** Total matches for the same filters, for the "N results" label. */
export function usePaperCount(teamId: string, q: string, tag: string | null) {
  return useQuery({
    queryKey: ["paper-count", teamId, q, tag],
    queryFn: async (): Promise<number> => {
      const { data, error } = await supabase.rpc("search_papers_count", {
        p_team: teamId,
        p_q: q,
        p_tag: tag,
      });
      if (error) throw error;
      return (data ?? 0) as number;
    },
  });
}
