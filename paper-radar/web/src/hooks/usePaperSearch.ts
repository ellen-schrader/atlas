import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";

export const PAGE_SIZE = 30;

/** How to order a lab's papers.
 *  "shared"    — when the lab posted it (default; right for a lab that grows one at a time)
 *  "published" — when the paper came out (right after importing a back-catalogue, where
 *                every post shares the same posted_at and "recently shared" says nothing) */
export type PaperSort = "shared" | "published";

/** Reading status — per *user*, not per lab: "unread" means unread by you.
 *  A paper you saved but haven't read is still unread; that's the point of a
 *  reading list. */
export type PaperStatus = "unread" | "to_read" | "reading" | "read";

export interface PaperFilters {
  tag: string | null;
  venue: string | null;
  status: PaperStatus | null;
}

export const NO_FILTERS: PaperFilters = { tag: null, venue: null, status: null };

export function activeFilterCount(f: PaperFilters): number {
  return [f.tag, f.venue, f.status].filter(Boolean).length;
}

/** Server-side, paginated full-text search over a lab's papers (search_papers
 *  RPC). Embeds the joined paper so the result reuses the PaperPost shape. */
export function usePaperSearch(
  teamId: string,
  q: string,
  filters: PaperFilters = NO_FILTERS,
  sort: PaperSort = "shared",
) {
  return useInfiniteQuery({
    queryKey: ["paper-search", teamId, q, filters, sort],
    initialPageParam: 0,
    queryFn: async ({ pageParam }): Promise<PaperPost[]> => {
      const { data, error } = await supabase
        .rpc("search_papers", {
          p_team: teamId,
          p_q: q,
          p_tag: filters.tag,
          p_venue: filters.venue,
          p_status: filters.status,
          p_limit: PAGE_SIZE,
          p_offset: pageParam,
          p_sort: sort,
        })
        .select(
          "id, posted_at, note, posted_by, posted_by_label, tags, papers(*), poster:profiles!paper_posts_posted_by_fkey(display_name)",
        );
      if (error) throw error;
      return (data ?? []) as unknown as PaperPost[];
    },
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length < PAGE_SIZE ? undefined : allPages.length * PAGE_SIZE,
  });
}

/** Total matches for the same filters, for the "N results" label. */
export function usePaperCount(teamId: string, q: string, filters: PaperFilters = NO_FILTERS) {
  return useQuery({
    // The count must use the SAME filters as the list, or the "N results" label
    // contradicts what's on screen.
    queryKey: ["paper-count", teamId, q, filters],
    queryFn: async (): Promise<number> => {
      const { data, error } = await supabase.rpc("search_papers_count", {
        p_team: teamId,
        p_q: q,
        p_tag: filters.tag,
        p_venue: filters.venue,
        p_status: filters.status,
      });
      if (error) throw error;
      return (data ?? 0) as number;
    },
  });
}
