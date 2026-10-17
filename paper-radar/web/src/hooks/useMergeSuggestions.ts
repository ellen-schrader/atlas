import { useQuery, useQueryClient } from "@tanstack/react-query";

import { invalidateAfterPost } from "@/lib/paperLookup";
import { supabase } from "@/lib/supabase";

export interface SuggestedPaper {
  id: string;
  title: string | null;
  authors: string[];
  venue: string | null;
  year: number | null;
  doi: string | null;
  url: string | null;
}

/** A preprint and a published paper in this lab that look like one piece of
 *  work but that nothing links (api/merge_suggestions.py). */
export interface MergeSuggestion {
  id: string;
  score: number;
  preprint: SuggestedPaper;
  published: SuggestedPaper;
}

const PAPER = "id, title, authors, venue, year, doi, url";

/** The lab's open suggestions, closest match first. */
export function useMergeSuggestions(teamId: string) {
  return useQuery({
    queryKey: ["merge-suggestions", teamId],
    queryFn: async (): Promise<MergeSuggestion[]> => {
      const { data, error } = await supabase
        .from("merge_suggestions")
        .select(
          `id, score, preprint:papers!merge_suggestions_preprint_id_fkey(${PAPER}), published:papers!merge_suggestions_published_id_fkey(${PAPER})`,
        )
        .eq("team_id", teamId)
        .eq("status", "pending")
        .order("score", { ascending: false });
      if (error) throw error;
      return ((data ?? []) as unknown as MergeSuggestion[]).filter((s) => s.preprint && s.published);
    },
  });
}

/** Merge the pair, or say they are not the same. Any lab member may do either
 *  (decide_merge_suggestion checks membership and that it is still open). */
export function useDecideMergeSuggestion(teamId: string) {
  const qc = useQueryClient();
  return async function decide(suggestionId: string, merge: boolean): Promise<void> {
    const { error } = await supabase.rpc("decide_merge_suggestion", {
      p_suggestion: suggestionId,
      p_merge: merge,
    });
    if (error) throw new Error(error.message);
    await qc.invalidateQueries({ queryKey: ["merge-suggestions", teamId] });
    if (merge) {
      // The preprint is gone from every list, and its comments, reactions and
      // reading status are on the published paper now.
      await invalidateAfterPost(qc, teamId);
      for (const key of ["paper-post", "reading-list", "read-papers", "engagement-counts", "preprint-links"]) {
        void qc.invalidateQueries({ queryKey: [key] });
      }
    }
  };
}
